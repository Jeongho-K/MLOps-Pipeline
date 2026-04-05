"""Prometheus metrics instrumentation for the serving API."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from prometheus_client import Counter, Gauge, Histogram
from prometheus_fastapi_instrumentator import Instrumentator

if TYPE_CHECKING:
    from fastapi import FastAPI

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


def setup_metrics(app: FastAPI) -> None:
    """Attach Prometheus instrumentator and expose /metrics endpoint.

    Args:
        app: FastAPI application instance.
    """
    instrumentator = Instrumentator(
        should_group_status_codes=True,
        excluded_handlers=["/metrics"],
    )
    instrumentator.instrument(app).expose(app, endpoint="/metrics")
    logger.info("Prometheus metrics enabled at /metrics")


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
