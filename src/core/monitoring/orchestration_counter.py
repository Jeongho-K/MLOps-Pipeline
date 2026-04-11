"""Orchestration-side Prometheus counter, kept separate from the FastAPI
serving metrics module so the Prefect worker image can import it without
pulling in FastAPI-specific dependencies.

Rationale: ``src/core/monitoring/metrics.py`` imports
``prometheus_fastapi_instrumentator`` at module top level, which is not
installed in the Prefect worker image. Worker-side trigger helpers must
record failures from inside the worker, so the counter and its recording
helper both live in this standalone module. The serving ``metrics.py``
re-exports the counter so the ``/metrics`` endpoint still surfaces the
value for Prometheus scrapes.

Invariants:
    Any new trigger site that narrow-catches an infra failure MUST
    register its trigger type in ``_KNOWN_TRIGGER_TYPES`` below and call
    :func:`record_trigger_failure` on its except branches. The taxonomy
    tuple is consumed by ``setup_metrics`` in the serving module to
    prime the labeled metric family so it is visible at ``/metrics``
    before any real failure has occurred — Prometheus labeled counters
    do not export a metric family until ``.labels(...).inc()`` has been
    called at least once, and Phase E-3 notification block wiring needs
    the family to be scrapeable for PromQL alerting.
"""

from __future__ import annotations

import logging

from prometheus_client import Counter

logger = logging.getLogger(__name__)

ORCHESTRATION_TRIGGER_FAILURE_COUNTER = Counter(
    "orchestration_trigger_failure_total",
    "Failed orchestration trigger attempts (narrow-caught).",
    labelnames=("trigger_type", "error_class"),
)

# Canonical taxonomy of narrow-catch trigger sites. Consumed by
# ``metrics.setup_metrics`` to prime the metric family per worker.
_KNOWN_TRIGGER_TYPES: tuple[str, ...] = (
    "ct_on_drift",
    "rollback",
    "al_on_medium_drift",
    "ct_on_labeling",
    "ct_on_accumulation",
)


def record_trigger_failure(trigger_type: str, exc: BaseException) -> None:
    """Increment the orchestration trigger failure counter and log ERROR.

    Used by narrow ``except`` blocks in the trigger helpers across
    ``monitoring_flow``, ``data_accumulation_flow`` and the labeling
    webhook. Kept in this FastAPI-free module so worker-side call sites
    can import it without pulling in serving dependencies.

    Args:
        trigger_type: One of :data:`_KNOWN_TRIGGER_TYPES`. The caller is
            responsible for passing a registered value; unregistered
            types still record but will not appear in the primed metric
            family at startup.
        exc: The narrow-caught exception. Its class name is used as the
            ``error_class`` label so PromQL can group failures by kind.
    """
    ORCHESTRATION_TRIGGER_FAILURE_COUNTER.labels(
        trigger_type=trigger_type,
        error_class=type(exc).__name__,
    ).inc()
    logger.error(
        "Orchestration trigger failed: trigger_type=%s error=%s",
        trigger_type,
        type(exc).__name__,
        exc_info=True,
    )
