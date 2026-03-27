"""Prometheus metrics instrumentation for the serving API."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from prometheus_client import Counter, Histogram
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
