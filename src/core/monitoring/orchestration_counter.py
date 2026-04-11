"""Orchestration-side Prometheus counter, kept separate from the FastAPI
serving metrics module so the Prefect worker image can import it without
pulling in FastAPI-specific dependencies.

Rationale: ``src/core/monitoring/metrics.py`` imports
``prometheus_fastapi_instrumentator`` at module top level, which is not
installed in the Prefect worker image. The monitoring flow's narrow-catch
trigger helpers must record failures from inside the worker, so the counter
lives in this standalone module. The serving ``metrics.py`` re-exports it so
the ``/metrics`` endpoint still surfaces the value for Prometheus scrapes.
"""

from __future__ import annotations

from prometheus_client import Counter

ORCHESTRATION_TRIGGER_FAILURE_COUNTER = Counter(
    "orchestration_trigger_failure_total",
    "Failed orchestration trigger attempts (narrow-caught).",
    labelnames=("trigger_type", "error_class"),
)
