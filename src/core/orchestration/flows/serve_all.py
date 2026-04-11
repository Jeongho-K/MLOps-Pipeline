"""Unified Prefect deployment server for the active-learning data flywheel.

Registers all four core flows as `RunnerDeployment`s on the local Prefect
server and serves them from a single long-lived worker process:

    continuous-training-deployment       event-driven (webhook / drift / accumulation)
    active-learning-deployment           event-driven (G5 medium drift)
    monitoring-deployment                cron: daily 03:00 UTC
    data-accumulation-deployment         cron: every 6 hours

Replaces the former `continuous_training_serve.py`, which only served the
continuous-training flow and left the other three flows unregistered — which
in turn silently broke `run_deployment()` calls from `monitoring_flow` and
`data_accumulation_flow`.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from prefect import serve

from src.core.monitoring.evidently.config import DriftConfig
from src.core.orchestration.config import ContinuousTrainingConfig
from src.core.orchestration.flows.active_learning_flow import active_learning_flow
from src.core.orchestration.flows.continuous_training_flow import continuous_training_flow
from src.core.orchestration.flows.data_accumulation_flow import data_accumulation_flow
from src.core.orchestration.flows.monitoring_flow import monitoring_pipeline

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


# Cron schedules for periodic flows. Event-driven flows (CT, AL) intentionally
# have no schedule: they run only when explicitly triggered via run_deployment.
MONITORING_CRON = "0 3 * * *"  # daily at 03:00 UTC
DATA_ACCUMULATION_CRON = "0 */6 * * *"  # every 6 hours

# Worker-side Prometheus metrics HTTP server port. The Prefect worker is a
# long-running process (``prefect.serve`` blocks), so its own in-process
# Prometheus registry must be exposed as a second scrape target alongside the
# api container — api ``/metrics`` cannot see this process's counter state.
WORKER_METRICS_PORT = 9092


def _start_metrics_server(port: int = WORKER_METRICS_PORT) -> None:
    """Start a Prometheus metrics HTTP endpoint for the worker process.

    The worker-side trigger helpers in ``monitoring_flow`` and
    ``data_accumulation_flow`` increment
    ``ORCHESTRATION_TRIGGER_FAILURE_COUNTER`` into the current process's
    in-process registry. The api container's ``/metrics`` endpoint lives in a
    different process (and under gunicorn multiproc) and cannot see these
    increments. To make worker-side failures observable to Prometheus we
    expose the worker's own registry on a local HTTP endpoint that Prometheus
    scrapes as a separate job (see ``configs/prometheus/prometheus.yml``).

    Prime every entry in ``_KNOWN_TRIGGER_TYPES`` with an ``error_class='none'``
    zero sample so the labeled metric family is visible to Prometheus before
    any real failure has occurred. Mirrors the api-side
    ``setup_metrics`` prime loop introduced in Phase E-2 post-audit.

    ``prometheus_client.start_http_server`` spawns a daemon thread and
    returns, so this call is non-blocking and survives for the lifetime of
    the parent process.

    Args:
        port: TCP port to bind the metrics HTTP server to. Defaults to
            :data:`WORKER_METRICS_PORT`.
    """
    from prometheus_client import start_http_server

    from src.core.monitoring.orchestration_counter import (
        _KNOWN_TRIGGER_TYPES,
        ORCHESTRATION_TRIGGER_FAILURE_COUNTER,
    )

    for trigger_type in _KNOWN_TRIGGER_TYPES:
        ORCHESTRATION_TRIGGER_FAILURE_COUNTER.labels(
            trigger_type=trigger_type,
            error_class="none",
        ).inc(0)

    start_http_server(port)
    logger.info("Worker metrics server listening on :%d", port)


def _build_continuous_training_parameters(cfg: ContinuousTrainingConfig) -> dict[str, Any]:
    """Mirror the parameter set that the former CT-only serve script used.

    Args:
        cfg: Continuous training configuration loaded from ``CT_*`` env vars.

    Returns:
        Keyword-argument dictionary for ``continuous_training_flow``.
    """
    return {
        "trigger_source": "manual",
        "s3_endpoint": cfg.s3_endpoint,
        "s3_access_key": cfg.s3_access_key,
        "s3_secret_key": cfg.s3_secret_key,
        "merged_data_dir": cfg.merged_data_dir,
        "train_val_split": cfg.train_val_split,
        "label_studio_url": cfg.label_studio_url,
        "label_studio_api_key": cfg.label_studio_api_key,
        "label_studio_project_id": cfg.label_studio_project_id,
        "mlflow_tracking_uri": cfg.mlflow_tracking_uri,
        "registered_model_name": cfg.registered_model_name,
        "min_val_accuracy": cfg.min_val_accuracy,
        "max_overfit_gap": cfg.max_overfit_gap,
        "champion_metric": cfg.champion_metric,
        "champion_margin": cfg.champion_margin,
        "round_state_bucket": cfg.round_state_bucket,
        "round_state_key": cfg.round_state_key,
    }


def _build_active_learning_parameters(
    ct_cfg: ContinuousTrainingConfig,
    drift_cfg: DriftConfig,
) -> dict[str, Any]:
    """Build AL flow parameters by reusing CT and Drift configs.

    Avoids introducing a bespoke settings class: S3 credentials and
    Label Studio settings come from ``ContinuousTrainingConfig`` while
    the prediction-logs bucket name comes from ``DriftConfig``.

    Args:
        ct_cfg: Continuous training configuration (``CT_*`` env vars).
        drift_cfg: Drift detection configuration (``DRIFT_*`` env vars).

    Returns:
        Keyword-argument dictionary for ``active_learning_flow``.
    """
    return {
        "s3_endpoint": ct_cfg.s3_endpoint,
        "s3_access_key": ct_cfg.s3_access_key,
        "s3_secret_key": ct_cfg.s3_secret_key,
        "prediction_logs_bucket": drift_cfg.prediction_logs_bucket,
        "label_studio_url": ct_cfg.label_studio_url,
        "label_studio_api_key": ct_cfg.label_studio_api_key,
        "label_studio_project_id": ct_cfg.label_studio_project_id,
    }


def _build_data_accumulation_parameters(cfg: ContinuousTrainingConfig) -> dict[str, Any]:
    """Build data-accumulation flow parameters from the CT config.

    Reuses the CT S3 credentials and the ``round_state_bucket`` as the
    accumulation bucket so that no new environment variables are required.

    Args:
        cfg: Continuous training configuration (``CT_*`` env vars).

    Returns:
        Keyword-argument dictionary for ``data_accumulation_flow``.
    """
    return {
        "s3_endpoint": cfg.s3_endpoint,
        "s3_access_key": cfg.s3_access_key,
        "s3_secret_key": cfg.s3_secret_key,
        "accumulation_bucket": cfg.round_state_bucket,
        "trigger_retraining": True,
    }


def main() -> None:
    """Register and serve all four flow deployments."""
    prefect_api_url = os.environ.get("PREFECT_API_URL", "http://prefect-server:4200/api")
    os.environ["PREFECT_API_URL"] = prefect_api_url
    logger.info("Using Prefect API at %s", prefect_api_url)

    ct_cfg = ContinuousTrainingConfig()
    drift_cfg = DriftConfig()

    ct_deployment = continuous_training_flow.to_deployment(
        name="continuous-training-deployment",
        tags=["continuous-training", "phase-b"],
        description="Event-driven retrain triggered by webhook, drift, or accumulation.",
        parameters=_build_continuous_training_parameters(ct_cfg),
    )

    al_deployment = active_learning_flow.to_deployment(
        name="active-learning-deployment",
        tags=["active-learning", "phase-a"],
        description="Collect uncertain samples into Label Studio when drift is medium.",
        parameters=_build_active_learning_parameters(ct_cfg, drift_cfg),
    )

    monitoring_deployment = monitoring_pipeline.to_deployment(
        name="monitoring-deployment",
        tags=["monitoring", "phase-6"],
        description="Daily drift detection over the lookback window.",
        cron=MONITORING_CRON,
        parameters={},  # monitoring_pipeline resolves defaults from DriftConfig
    )

    accumulation_deployment = data_accumulation_flow.to_deployment(
        name="data-accumulation-deployment",
        tags=["data-accumulation", "phase-a"],
        description="Periodic pseudo-label validation; triggers retrain when accepted.",
        cron=DATA_ACCUMULATION_CRON,
        parameters=_build_data_accumulation_parameters(ct_cfg),
    )

    deployments = (
        ct_deployment,
        al_deployment,
        monitoring_deployment,
        accumulation_deployment,
    )
    logger.info(
        "Serving %d deployments: %s",
        len(deployments),
        ", ".join(d.name for d in deployments),
    )

    # Start the worker-side metrics HTTP endpoint before the blocking serve()
    # call. ``prometheus_client.start_http_server`` runs in a daemon thread so
    # it does not block the serve loop.
    _start_metrics_server()

    try:
        serve(*deployments)
    except KeyboardInterrupt:
        logger.info("Deployment serve interrupted by user. Shutting down.")
    except Exception:
        logger.exception(
            "Failed to serve deployments. Check PREFECT_API_URL (%s).",
            os.environ.get("PREFECT_API_URL", "not set"),
        )
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
