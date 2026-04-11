"""Regression tests for the Label Studio webhook trigger path.

The original webhook handler caught ``Exception`` and logged a warning,
silently returning HTTP 200 even when the Prefect trigger failed. These
tests pin the narrowed catch scope so the Phase E-2 S5-class regression
(unknown kwarg swallowed as a no-op) cannot recur on the labeling path.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import MagicMock, patch

from src.core.active_learning.labeling import webhook as webhook_module


class TestWebhookNarrowExceptionHandling:
    @staticmethod
    def _counter_value(trigger_type: str, error_class: str) -> float:
        from src.core.monitoring.metrics import (
            ORCHESTRATION_TRIGGER_FAILURE_COUNTER,
        )

        return ORCHESTRATION_TRIGGER_FAILURE_COUNTER.labels(
            trigger_type=trigger_type,
            error_class=error_class,
        )._value.get()

    @staticmethod
    def _reset_debounce() -> None:
        webhook_module._last_trigger_time = 0.0

    def _bridge_mock(self, count: int = 999) -> MagicMock:
        bridge = MagicMock()
        bridge.get_annotation_count.return_value = count
        return bridge

    def test_prefect_exception_from_run_deployment_is_caught_and_counted(
        self,
    ) -> None:
        """A PrefectException during run_deployment → counter tick, no raise."""
        from prefect.exceptions import PrefectException

        self._reset_debounce()
        before = self._counter_value("ct_on_labeling", "PrefectException")

        async def boom(*_args: Any, **_kwargs: Any) -> None:
            raise PrefectException("deployment missing")

        with (
            patch(
                "src.core.active_learning.labeling.bridge.LabelStudioBridge",
                return_value=self._bridge_mock(count=999),
            ),
            patch("prefect.deployments.run_deployment", side_effect=boom),
        ):
            asyncio.run(webhook_module._maybe_trigger_retraining(project_id=1))

        after = self._counter_value("ct_on_labeling", "PrefectException")
        assert after == before + 1

    def test_unexpected_exception_propagates_out_of_handler(self) -> None:
        """A plain ValueError must escape so FastAPI returns 500 and Label
        Studio retries — silent 200 OK is the exact anti-pattern we removed."""
        self._reset_debounce()

        bridge = MagicMock()
        bridge.get_annotation_count.side_effect = ValueError("real bug")

        with patch(
            "src.core.active_learning.labeling.bridge.LabelStudioBridge",
            return_value=bridge,
        ):
            try:
                asyncio.run(
                    webhook_module._maybe_trigger_retraining(project_id=1)
                )
            except ValueError:
                return

        raise AssertionError(
            "ValueError was silently swallowed — narrow catch regression"
        )
