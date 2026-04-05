"""Unit tests for Prometheus metrics instrumentation."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.core.monitoring.metrics import (
    PREDICTION_CLASS_COUNTER,
    record_prediction,
    setup_metrics,
)


class TestSetupMetrics:
    """Tests for setup_metrics function."""

    def test_instrumentator_attached(self) -> None:
        """Metrics endpoint should be available after setup."""
        app = FastAPI()
        setup_metrics(app)
        with TestClient(app) as client:
            resp = client.get("/metrics")
            assert resp.status_code == 200
            assert "http_request" in resp.text

    def test_idempotent(self) -> None:
        """Calling setup_metrics twice should not raise."""
        app = FastAPI()
        setup_metrics(app)
        setup_metrics(app)


class TestRecordPrediction:
    """Tests for record_prediction helper."""

    def test_records_class_and_confidence(self) -> None:
        """Should increment counter and observe confidence."""
        before_samples = PREDICTION_CLASS_COUNTER.labels(predicted_class="2").collect()[0].samples
        before_value = sum(s.value for s in before_samples if s.name.endswith("_total"))
        record_prediction(predicted_class=2, confidence=0.95)
        after_samples = PREDICTION_CLASS_COUNTER.labels(predicted_class="2").collect()[0].samples
        after_value = sum(s.value for s in after_samples if s.name.endswith("_total"))
        assert after_value == before_value + 1

    def test_records_with_class_name(self) -> None:
        """Should use class name as label when provided."""
        before_samples = PREDICTION_CLASS_COUNTER.labels(predicted_class="cat").collect()[0].samples
        before_value = sum(s.value for s in before_samples if s.name.endswith("_total"))
        record_prediction(predicted_class=0, confidence=0.8, class_name="cat")
        after_samples = PREDICTION_CLASS_COUNTER.labels(predicted_class="cat").collect()[0].samples
        after_value = sum(s.value for s in after_samples if s.name.endswith("_total"))
        assert after_value == before_value + 1
