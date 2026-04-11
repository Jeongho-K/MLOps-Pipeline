"""Prometheus metrics instrumentation for the serving API.

Supports gunicorn multi-worker setups via ``PROMETHEUS_MULTIPROC_DIR``.
When that environment variable is set, prometheus_client stores metric
state in shared mmap files under the directory, and ``/metrics`` reads
via ``MultiProcessCollector`` so all workers' counters are visible to
Prometheus scrapes.
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    REGISTRY,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
    multiprocess,
)
from prometheus_fastapi_instrumentator import Instrumentator
from starlette.responses import Response

if TYPE_CHECKING:
    from fastapi import FastAPI
    from starlette.requests import Request

logger = logging.getLogger(__name__)

PREDICTION_CLASS_COUNTER = Counter(
    "prediction_class_total",
    "Total predictions per class",
    labelnames=("predicted_class",),
)

PREDICTION_CONFIDENCE_HISTOGRAM = Histogram(
    "prediction_confidence",
    "Distribution of prediction confidence scores",
    buckets=(0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 0.95, 0.99, 1.0),
)


ROUTING_DECISION_COUNTER = Counter(
    "al_routing_decision_total",
    "Predictions routed by confidence router",
    labelnames=("decision",),
)

UNCERTAINTY_HISTOGRAM = Histogram(
    "al_uncertainty_score",
    "Distribution of uncertainty scores",
    buckets=(0.05, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0),
)

ACCUMULATION_BUFFER_GAUGE = Gauge(
    "al_accumulation_buffer_size",
    "Current number of samples in the auto-accumulation buffer",
)

# Re-exported from orchestration_counter so the FastAPI /metrics endpoint
# surfaces it. The canonical definition lives in a FastAPI-free module because
# the Prefect worker image does not ship prometheus_fastapi_instrumentator.
from src.core.monitoring.orchestration_counter import (  # noqa: E402, F401
    ORCHESTRATION_TRIGGER_FAILURE_COUNTER,
)


def setup_metrics(app: FastAPI) -> None:
    """Attach Prometheus instrumentation and expose ``/metrics``.

    In multi-worker gunicorn setups, ``PROMETHEUS_MULTIPROC_DIR`` must be
    set to a writable directory. When present, metric state is shared
    across workers and ``/metrics`` serves a merged view via
    ``MultiProcessCollector``. When unset, the default in-process
    ``REGISTRY`` is used (single-worker / dev mode).

    Args:
        app: FastAPI application instance.
    """
    instrumentator = Instrumentator(
        should_group_status_codes=True,
        excluded_handlers=["/metrics"],
    )
    instrumentator.instrument(app)

    multiproc_dir = os.environ.get("PROMETHEUS_MULTIPROC_DIR")

    if multiproc_dir:
        # Build a per-request registry that merges all workers' mmap files.
        async def _render_multiprocess_metrics(_request: Request) -> Response:
            registry = CollectorRegistry()
            multiprocess.MultiProcessCollector(registry)
            data = generate_latest(registry)
            return Response(content=data, media_type=CONTENT_TYPE_LATEST)

        app.add_route("/metrics", _render_multiprocess_metrics)
        logger.info(
            "Prometheus metrics enabled at /metrics (multiprocess dir=%s)",
            multiproc_dir,
        )
    else:

        async def _render_inprocess_metrics(_request: Request) -> Response:
            data = generate_latest(REGISTRY)
            return Response(content=data, media_type=CONTENT_TYPE_LATEST)

        app.add_route("/metrics", _render_inprocess_metrics)
        logger.info("Prometheus metrics enabled at /metrics (in-process)")

    # Prime orchestration_trigger_failure_total so the labeled metric family
    # is scrapeable before any real failure occurs. In multiproc mode this
    # runs inside each gunicorn worker after fork, so every worker writes
    # its own mmap entry; MultiProcessCollector merges them at scrape time.
    # Without this, Phase E-3 notification-block wiring cannot define a
    # PromQL alert on a metric family that has never been emitted.
    from src.core.monitoring.orchestration_counter import _KNOWN_TRIGGER_TYPES

    for _trigger_type in _KNOWN_TRIGGER_TYPES:
        ORCHESTRATION_TRIGGER_FAILURE_COUNTER.labels(
            trigger_type=_trigger_type,
            error_class="none",
        ).inc(0)


def record_prediction(
    predicted_class: int,
    confidence: float,
    class_name: str | None = None,
) -> None:
    """Record a prediction in Prometheus metrics.

    Args:
        predicted_class: Predicted class index.
        confidence: Confidence score (0-1).
        class_name: Human-readable class name (used as label if provided).
    """
    label = class_name if class_name is not None else str(predicted_class)
    PREDICTION_CLASS_COUNTER.labels(predicted_class=label).inc()
    PREDICTION_CONFIDENCE_HISTOGRAM.observe(confidence)


def record_routing(
    routing_decision: str,
    uncertainty_score: float,
    accumulation_buffer_size: int | None = None,
) -> None:
    """Record Active Learning routing metrics.

    Args:
        routing_decision: The routing decision (auto_accumulate, human_review, discard).
        uncertainty_score: Uncertainty score for the prediction.
        accumulation_buffer_size: Current accumulator buffer size, if available.
    """
    ROUTING_DECISION_COUNTER.labels(decision=routing_decision).inc()
    UNCERTAINTY_HISTOGRAM.observe(uncertainty_score)
    if accumulation_buffer_size is not None:
        ACCUMULATION_BUFFER_GAUGE.set(accumulation_buffer_size)
