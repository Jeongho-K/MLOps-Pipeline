"""Unit tests for ``src.core.monitoring.metrics.setup_metrics``.

These tests pin the contract that ``setup_metrics`` primes the labeled
``orchestration_trigger_failure_total`` counter family so it is visible
at ``/metrics`` before any real failure occurs. Without this prime,
Phase E-3 notification-block wiring cannot define PromQL alerts on the
metric family because ``prometheus_client`` omits labeled metric
families until ``.labels(...).inc()`` has been called at least once.

Unit tests run without ``PROMETHEUS_MULTIPROC_DIR`` set, so
``setup_metrics`` takes the in-process branch and the prime writes to
the default ``REGISTRY``. Multi-worker mmap correctness is verified
separately by Layer 3 runtime E2E (``curl /metrics`` against the live
api container).
"""

from __future__ import annotations


class TestSetupMetricsPrimesOrchestrationCounter:
    """``setup_metrics`` must prime every entry in ``_KNOWN_TRIGGER_TYPES``."""

    def test_primes_all_known_trigger_types(self) -> None:
        from fastapi import FastAPI
        from prometheus_client import REGISTRY

        from src.core.monitoring.metrics import setup_metrics
        from src.core.monitoring.orchestration_counter import (
            _KNOWN_TRIGGER_TYPES,
        )

        app = FastAPI()
        setup_metrics(app)

        for trigger_type in _KNOWN_TRIGGER_TYPES:
            sample = REGISTRY.get_sample_value(
                "orchestration_trigger_failure_total",
                {"trigger_type": trigger_type, "error_class": "none"},
            )
            assert sample is not None, (
                f"trigger_type={trigger_type} not primed — "
                "_KNOWN_TRIGGER_TYPES and setup_metrics drifted"
            )

    def test_preserves_metrics_route(self) -> None:
        """A prime that silently broke the ``/metrics`` route would
        defeat the purpose. This guards the route-attachment contract
        against future prime-related regressions."""
        from fastapi import FastAPI

        from src.core.monitoring.metrics import setup_metrics

        app = FastAPI()
        setup_metrics(app)

        metrics_routes = [
            route
            for route in app.routes
            if getattr(route, "path", None) == "/metrics"
        ]
        assert metrics_routes, "/metrics route was lost after setup_metrics"
