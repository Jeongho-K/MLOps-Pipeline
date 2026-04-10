"""Unit tests for the unified Prefect deployment server."""

from __future__ import annotations

import importlib
import sys
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from prefect.deployments.runner import RunnerDeployment


@pytest.fixture
def serve_all_module(monkeypatch: pytest.MonkeyPatch):
    """Import serve_all with a captured fake serve() and minimal env.

    DriftConfig has required ``DRIFT_S3_ACCESS_KEY`` / ``DRIFT_S3_SECRET_KEY``
    fields. Set them to dummies so instantiation inside serve_all.main works.
    """
    monkeypatch.setenv("DRIFT_S3_ACCESS_KEY", "test-access")
    monkeypatch.setenv("DRIFT_S3_SECRET_KEY", "test-secret")
    monkeypatch.setenv("PREFECT_API_URL", "http://prefect-server-test:4200/api")

    sys.modules.pop("src.core.orchestration.flows.serve_all", None)
    module = importlib.import_module("src.core.orchestration.flows.serve_all")

    captured: dict[str, tuple[RunnerDeployment, ...]] = {}

    def fake_serve(*deployments: RunnerDeployment, **_kwargs: object) -> None:
        captured["deployments"] = deployments

    monkeypatch.setattr(module, "serve", fake_serve)
    return module, captured


def test_serve_all_registers_four_named_deployments(serve_all_module):
    module, captured = serve_all_module

    module.main()

    deployments = captured["deployments"]
    assert len(deployments) == 4

    names = sorted(d.name for d in deployments)
    assert names == [
        "active-learning-deployment",
        "continuous-training-deployment",
        "data-accumulation-deployment",
        "monitoring-deployment",
    ]


def test_event_driven_deployments_have_no_schedule(serve_all_module):
    """CT and AL are triggered by webhook/drift — they must not self-schedule."""
    module, captured = serve_all_module
    module.main()

    by_name = {d.name: d for d in captured["deployments"]}
    assert by_name["continuous-training-deployment"].schedules == []
    assert by_name["active-learning-deployment"].schedules == []


def test_periodic_deployments_have_cron_schedules(serve_all_module):
    """Monitoring (daily) and data accumulation (6h) must have cron schedules."""
    module, captured = serve_all_module
    module.main()

    by_name = {d.name: d for d in captured["deployments"]}

    monitoring_schedules = by_name["monitoring-deployment"].schedules
    assert len(monitoring_schedules) == 1
    assert getattr(monitoring_schedules[0].schedule, "cron", None) == module.MONITORING_CRON

    accumulation_schedules = by_name["data-accumulation-deployment"].schedules
    assert len(accumulation_schedules) == 1
    assert getattr(accumulation_schedules[0].schedule, "cron", None) == module.DATA_ACCUMULATION_CRON


def test_active_learning_deployment_reuses_ct_and_drift_config(serve_all_module):
    """AL deployment parameters should come from ContinuousTrainingConfig
    and DriftConfig — no bespoke settings class."""
    module, captured = serve_all_module
    module.main()

    by_name = {d.name: d for d in captured["deployments"]}
    al_params = by_name["active-learning-deployment"].parameters

    assert al_params["s3_endpoint"] == "http://minio:9000"
    assert al_params["s3_access_key"] == ""  # CT default; overridden via CT_S3_ACCESS_KEY in prod
    assert al_params["prediction_logs_bucket"] == "prediction-logs"  # DriftConfig default
    assert al_params["label_studio_url"] == "http://label-studio:8080"


def test_continuous_training_deployment_mirrors_original_parameters(serve_all_module):
    """Ensure the CT deployment retains the superset of params the old
    continuous_training_serve.py used, so existing run_deployment callers
    keep working."""
    module, captured = serve_all_module
    module.main()

    by_name = {d.name: d for d in captured["deployments"]}
    ct_params = by_name["continuous-training-deployment"].parameters

    expected_keys = {
        "trigger_source",
        "s3_endpoint",
        "s3_access_key",
        "s3_secret_key",
        "merged_data_dir",
        "train_val_split",
        "label_studio_url",
        "label_studio_api_key",
        "label_studio_project_id",
        "mlflow_tracking_uri",
        "registered_model_name",
        "min_val_accuracy",
        "max_overfit_gap",
        "champion_metric",
        "champion_margin",
        "round_state_bucket",
        "round_state_key",
    }
    assert expected_keys.issubset(ct_params.keys())
    assert ct_params["trigger_source"] == "manual"
