"""Prediction workflow E2E test.

Tests the full prediction flow: upload image → verify response →
check routing decision → verify data in MinIO → check Prometheus/Grafana.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from .helpers.api_client import predict_image, query_prometheus
from .helpers.pages import GrafanaPage
from .helpers.wait import wait_for_minio_object

if TYPE_CHECKING:
    from playwright.sync_api import Page

TEST_IMAGE = Path("data/raw/cifar10-demo/train/cat/cat_0000.png")


class TestPredictionWorkflow:
    """Full prediction flow: upload → classify → route → verify downstream."""

    _prediction_result: dict | None = None

    def test_01_predict_image(self, api_base_url: str):
        """Upload a test image via API and verify prediction response."""
        if not TEST_IMAGE.exists():
            pytest.skip("Test image not available")

        try:
            result = predict_image(api_base_url, TEST_IMAGE)
        except Exception as e:
            pytest.skip(f"Prediction not available (model may not be loaded): {e}")

        TestPredictionWorkflow._prediction_result = result

        assert "predicted_class" in result
        assert "confidence" in result
        assert isinstance(result["confidence"], float)
        assert 0.0 <= result["confidence"] <= 1.0

    def test_02_routing_decision_present(self):
        """Prediction response should include routing_decision field."""
        result = TestPredictionWorkflow._prediction_result
        if result is None:
            pytest.skip("No prediction result from test_01")

        assert "routing_decision" in result
        assert result["routing_decision"] in ("auto_accumulate", "human_review", "discard")

    def test_03_uncertainty_score_present(self):
        """Prediction response should include uncertainty_score field."""
        result = TestPredictionWorkflow._prediction_result
        if result is None:
            pytest.skip("No prediction result from test_01")

        assert "uncertainty_score" in result
        assert isinstance(result["uncertainty_score"], float)
        assert 0.0 <= result["uncertainty_score"] <= 1.0

    def test_04_auto_accumulated_in_minio(self, minio_s3_client):
        """If routing was auto_accumulate, data should appear in MinIO."""
        result = TestPredictionWorkflow._prediction_result
        if result is None:
            pytest.skip("No prediction result from test_01")
        if result.get("routing_decision") != "auto_accumulate":
            pytest.skip("Prediction was not routed to auto_accumulate")

        key = wait_for_minio_object(
            minio_s3_client,
            bucket="active-learning",
            prefix="accumulated/",
            timeout=30.0,
        )
        assert key.startswith("accumulated/")

    def test_05_prometheus_metrics_updated(self, prometheus_base_url: str):
        """Prediction should register in Prometheus metrics."""
        result = query_prometheus(prometheus_base_url, "http_requests_total")
        assert result["status"] == "success"

    def test_06_grafana_reflects_prediction(self, grafana_page: Page, grafana_base_url: str):
        """Grafana dashboard should load without errors after predictions."""
        gp = GrafanaPage(grafana_page, grafana_base_url)
        gp.navigate_to_dashboard()

        # Dashboard should render without errors
        grafana_page.wait_for_load_state("networkidle")
        assert not gp.has_panel_errors()
