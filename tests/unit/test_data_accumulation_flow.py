"""Unit tests for Data Accumulation pipeline flow."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest


class TestDataAccumulationFlow:
    """Tests for data_accumulation_flow."""

    def test_flow_completes_with_valid_samples(self):
        from src.core.orchestration.flows.data_accumulation_flow import data_accumulation_flow

        samples = [
            {"predicted_class": "cat", "confidence": 0.98, "_s3_key": "accumulated/a.jsonl"},
            {"predicted_class": "dog", "confidence": 0.97, "_s3_key": "accumulated/a.jsonl"},
        ]
        quality_result = {
            "passed": True,
            "reason": "All checks passed",
            "stats": {"num_samples": 2},
        }

        with (
            patch(
                "src.core.orchestration.flows.data_accumulation_flow.fetch_accumulated_samples",
                return_value=samples,
            ),
            patch(
                "src.core.orchestration.flows.data_accumulation_flow.validate_accumulation_quality",
                return_value=quality_result,
            ),
            patch(
                "src.core.orchestration.flows.data_accumulation_flow.cleanup_accumulated",
                return_value=1,
            ),
            patch("src.core.orchestration.flows.data_accumulation_flow.create_markdown_artifact"),
        ):
            result = data_accumulation_flow.fn()

        assert result["status"] == "completed"
        assert result["total_samples"] == 2
        assert result["quality_gate_passed"] is True
        assert result["files_cleaned"] == 1

    def test_flow_blocks_on_quality_gate_failure(self):
        from src.core.orchestration.flows.data_accumulation_flow import data_accumulation_flow

        samples = [{"predicted_class": "cat", "confidence": 0.98}] * 10
        quality_result = {
            "passed": False,
            "reason": "Insufficient samples: 10 < 50",
            "stats": {"num_samples": 10},
        }

        with (
            patch(
                "src.core.orchestration.flows.data_accumulation_flow.fetch_accumulated_samples",
                return_value=samples,
            ),
            patch(
                "src.core.orchestration.flows.data_accumulation_flow.validate_accumulation_quality",
                return_value=quality_result,
            ),
            patch(
                "src.core.orchestration.flows.data_accumulation_flow.cleanup_accumulated",
            ) as mock_cleanup,
            patch("src.core.orchestration.flows.data_accumulation_flow.create_markdown_artifact"),
        ):
            result = data_accumulation_flow.fn()

        assert result["quality_gate_passed"] is False
        assert "Insufficient samples" in result["reason"]
        mock_cleanup.assert_not_called()

    def test_flow_handles_empty_accumulation(self):
        from src.core.orchestration.flows.data_accumulation_flow import data_accumulation_flow

        with (
            patch(
                "src.core.orchestration.flows.data_accumulation_flow.fetch_accumulated_samples",
                return_value=[],
            ),
            patch("src.core.orchestration.flows.data_accumulation_flow.create_markdown_artifact"),
        ):
            result = data_accumulation_flow.fn()

        assert result["status"] == "completed"
        assert result["total_samples"] == 0
        assert result["quality_gate_passed"] is False
        assert result["files_cleaned"] == 0

    def test_flow_skips_cleanup_when_quality_fails(self):
        from src.core.orchestration.flows.data_accumulation_flow import data_accumulation_flow

        samples = [{"predicted_class": "cat", "confidence": 0.95}] * 90 + [
            {"predicted_class": "dog", "confidence": 0.95}
        ] * 10
        quality_result = {
            "passed": False,
            "reason": "Class imbalance: class 'cat' has 90.0% of samples (threshold: 80%)",
            "stats": {
                "num_samples": 100,
                "class_distribution": {"cat": 90, "dog": 10},
                "max_class_ratio": 0.9,
            },
        }

        with (
            patch(
                "src.core.orchestration.flows.data_accumulation_flow.fetch_accumulated_samples",
                return_value=samples,
            ),
            patch(
                "src.core.orchestration.flows.data_accumulation_flow.validate_accumulation_quality",
                return_value=quality_result,
            ),
            patch(
                "src.core.orchestration.flows.data_accumulation_flow.cleanup_accumulated",
            ) as mock_cleanup,
            patch("src.core.orchestration.flows.data_accumulation_flow.create_markdown_artifact"),
        ):
            result = data_accumulation_flow.fn()

        assert result["quality_gate_passed"] is False
        assert "Class imbalance" in result["reason"]
        assert result["files_cleaned"] == 0
        mock_cleanup.assert_not_called()


class TestTriggerRetrainingNarrowCatch:
    """Regression tests: ``_trigger_retraining`` must narrow its catches so a
    broken Prefect path cannot silently degrade to a ``return False`` no-op.

    Mirrors ``test_monitoring_flow.TestNarrowTriggerExceptions`` for the
    ``ct_on_accumulation`` trigger type. Pins two invariants:
    (1) the ``_run_async(run_deployment(...))`` wrapper stays deleted, and
    (2) ``pydantic.ValidationError`` from missing ``CT_*`` env vars
    propagates loud — matching the monitoring_flow sibling semantic.
    """

    @staticmethod
    def _counter_value(trigger_type: str, error_class: str) -> float:
        from src.core.monitoring.orchestration_counter import (
            ORCHESTRATION_TRIGGER_FAILURE_COUNTER,
        )

        return ORCHESTRATION_TRIGGER_FAILURE_COUNTER.labels(
            trigger_type=trigger_type,
            error_class=error_class,
        )._value.get()

    def test_trigger_retraining_catches_prefect_exception(self) -> None:
        """PrefectException from run_deployment is caught and counted."""
        from prefect.exceptions import PrefectException

        from src.core.orchestration.flows.data_accumulation_flow import (
            _trigger_retraining,
        )

        before = self._counter_value("ct_on_accumulation", "PrefectException")

        def boom(*_args: Any, **_kwargs: Any) -> Any:
            raise PrefectException("deployment not found")

        with patch("prefect.deployments.run_deployment", side_effect=boom):
            result = _trigger_retraining()

        assert result is False
        after = self._counter_value("ct_on_accumulation", "PrefectException")
        assert after == before + 1

    def test_trigger_retraining_catches_import_error(self) -> None:
        """Missing prefect.deployments module is caught and counted.

        Uses the ``sys.modules[name] = None`` trick: Python's import
        machinery treats a ``None`` entry as a sentinel that forces
        ``ModuleNotFoundError`` (a subclass of ``ImportError``) on
        subsequent imports of that name. The narrow catch in
        ``_trigger_retraining`` catches ``ImportError``, which matches
        the ``ModuleNotFoundError`` subclass; the counter label is
        ``type(exc).__name__`` so it records ``ModuleNotFoundError``.
        """
        import sys

        from src.core.orchestration.flows.data_accumulation_flow import (
            _trigger_retraining,
        )

        before = self._counter_value("ct_on_accumulation", "ModuleNotFoundError")

        with patch.dict(sys.modules, {"prefect.deployments": None}):
            result = _trigger_retraining()

        assert result is False
        after = self._counter_value("ct_on_accumulation", "ModuleNotFoundError")
        assert after == before + 1

    def test_trigger_retraining_propagates_value_error(self) -> None:
        """A ValueError from run_deployment must NOT be swallowed.

        Pins the regression against re-introducing the broken
        ``_run_async(run_deployment(...))`` wrapper, which historically
        raised ``ValueError: a coroutine was expected``.
        """
        from src.core.orchestration.flows.data_accumulation_flow import (
            _trigger_retraining,
        )

        def boom(*_args: Any, **_kwargs: Any) -> Any:
            raise ValueError("a coroutine was expected")

        with (
            patch("prefect.deployments.run_deployment", side_effect=boom),
            pytest.raises(ValueError, match="coroutine"),
        ):
            _trigger_retraining()

    def test_trigger_retraining_propagates_validation_error(self) -> None:
        """Missing CT_* env vars surface as pydantic.ValidationError and
        must propagate — matches monitoring_flow sibling semantic."""
        from pydantic import BaseModel, ValidationError

        from src.core.orchestration.flows.data_accumulation_flow import (
            _trigger_retraining,
        )

        class _Required(BaseModel):
            x: int

        try:
            _Required(x="not an int")  # type: ignore[arg-type]
        except ValidationError as real_ve:
            fake_error = real_ve
        else:  # pragma: no cover
            raise AssertionError("pydantic ValidationError was not raised")

        fake_config_cls = MagicMock(side_effect=fake_error)

        with patch(
            "src.core.orchestration.config.ContinuousTrainingConfig",
            fake_config_cls,
        ), pytest.raises(ValidationError):
            _trigger_retraining()

    def test_trigger_retraining_success_returns_true_with_exact_call_args(
        self,
    ) -> None:
        """Happy path pins the contract: run_deployment called once with
        the exact parameters and NOT wrapped in asyncio.run — the deleted
        ``_run_async`` wrapper stays deleted.
        """
        from src.core.orchestration.config import ContinuousTrainingConfig
        from src.core.orchestration.flows.data_accumulation_flow import (
            _trigger_retraining,
        )

        expected_name = ContinuousTrainingConfig().deployment_name
        mock_run_deployment = MagicMock(return_value=MagicMock(name="FlowRun"))

        with patch(
            "prefect.deployments.run_deployment",
            mock_run_deployment,
        ):
            result = _trigger_retraining()

        assert result is True
        mock_run_deployment.assert_called_once_with(
            name=expected_name,
            parameters={"trigger_source": "data_accumulated"},
            timeout=0,
        )
