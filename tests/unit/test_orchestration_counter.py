"""Unit tests for ``src.core.monitoring.orchestration_counter``.

Covers the taxonomy pin (``_KNOWN_TRIGGER_TYPES``) and the promoted
``record_trigger_failure`` helper (previously ``_record_trigger_failure``
inside ``monitoring_flow``). Uses the delta pattern for counter
assertions so tests are order-independent against the global
``prometheus_client.REGISTRY``.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pytest


class TestKnownTriggerTypes:
    """Pin the taxonomy of narrow-catch trigger sites.

    Fails loud if a new trigger site is added without registering its
    type in ``_KNOWN_TRIGGER_TYPES``. Registration is the gate that
    makes the metric family visible in ``/metrics`` via the prime loop
    in ``setup_metrics``.
    """

    def test_known_trigger_types_matches_callsites(self) -> None:
        from src.core.monitoring.orchestration_counter import (
            _KNOWN_TRIGGER_TYPES,
        )

        expected = {
            "ct_on_drift",
            "rollback",
            "al_on_medium_drift",
            "ct_on_labeling",
            "ct_on_accumulation",
        }
        assert set(_KNOWN_TRIGGER_TYPES) == expected
        assert len(_KNOWN_TRIGGER_TYPES) == len(expected), (
            "duplicate entry in _KNOWN_TRIGGER_TYPES"
        )


class TestRecordTriggerFailure:
    """The promoted helper increments with the correct labels and logs ERROR."""

    @staticmethod
    def _counter_value(trigger_type: str, error_class: str) -> float:
        from src.core.monitoring.orchestration_counter import (
            ORCHESTRATION_TRIGGER_FAILURE_COUNTER,
        )

        return ORCHESTRATION_TRIGGER_FAILURE_COUNTER.labels(
            trigger_type=trigger_type,
            error_class=error_class,
        )._value.get()

    def test_increments_with_exception_class_label(self) -> None:
        from prefect.exceptions import PrefectException

        from src.core.monitoring.orchestration_counter import (
            record_trigger_failure,
        )

        before = self._counter_value("ct_on_drift", "PrefectException")
        record_trigger_failure("ct_on_drift", PrefectException("boom"))
        after = self._counter_value("ct_on_drift", "PrefectException")
        assert after == before + 1

    def test_handles_arbitrary_exception_class(self) -> None:
        """The helper does not filter — callers decide which exceptions
        to narrow. Passing a ValueError still counts (with error_class
        ``ValueError``) so the taxonomy never drops events."""
        from src.core.monitoring.orchestration_counter import (
            record_trigger_failure,
        )

        before = self._counter_value("ct_on_accumulation", "ValueError")
        record_trigger_failure("ct_on_accumulation", ValueError("x"))
        after = self._counter_value("ct_on_accumulation", "ValueError")
        assert after == before + 1

    def test_logs_error_level(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """After promotion, the logger name is the new module path.
        Guards against a stale caplog.set_level reference."""
        from src.core.monitoring.orchestration_counter import (
            record_trigger_failure,
        )

        caplog.set_level(
            logging.ERROR, logger="src.core.monitoring.orchestration_counter"
        )
        record_trigger_failure("rollback", RuntimeError("log me"))

        error_records = [
            r
            for r in caplog.records
            if r.levelno == logging.ERROR
            and "Orchestration trigger failed" in r.getMessage()
        ]
        assert error_records, (
            "record_trigger_failure must emit an ERROR log with the "
            "Orchestration trigger failed prefix"
        )
