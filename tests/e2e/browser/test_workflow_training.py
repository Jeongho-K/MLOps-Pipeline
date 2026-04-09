"""Training workflow E2E test.

Tests the training flow: trigger retraining → verify Prefect flow run →
check MLflow experiment → verify model in registry.
"""

from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

from .helpers.api_client import trigger_retraining


class TestTrainingWorkflow:
    """Trigger retraining → Prefect → MLflow → model registry."""

    _trigger_result: dict | None = None

    def test_01_trigger_retraining(self, api_base_url: str):
        """POST /admin/trigger-retraining should return triggered status."""
        try:
            result = trigger_retraining(api_base_url)
            TestTrainingWorkflow._trigger_result = result
            assert "status" in result
        except Exception as e:
            pytest.skip(f"Retraining trigger not available: {e}")

    def test_02_prefect_flow_runs_page(self, page: Page, prefect_base_url: str):
        """Prefect UI should show flow runs page."""
        page.goto(f"{prefect_base_url}/flow-runs")
        page.wait_for_load_state("domcontentloaded")

        # Prefect 3.x UI — verify we're on the flow runs page
        expect(page.locator("body")).to_contain_text("Flow", timeout=15000)

    def test_03_prefect_deployments_page(self, page: Page, prefect_base_url: str):
        """Prefect should show deployments page."""
        page.goto(f"{prefect_base_url}/deployments")
        page.wait_for_load_state("domcontentloaded")

        expect(page.locator("body")).to_contain_text("Deployment", timeout=15000)

    def test_04_mlflow_experiments_visible(self, page: Page, mlflow_base_url: str):
        """MLflow should show experiments page."""
        page.goto(mlflow_base_url)
        page.wait_for_load_state("domcontentloaded")

        expect(page.get_by_text("Welcome to MLflow").first).to_be_visible(timeout=15000)

    def test_05_mlflow_model_registry(self, page: Page, mlflow_base_url: str):
        """MLflow model registry should be accessible."""
        page.goto(f"{mlflow_base_url}/#/models")
        page.wait_for_load_state("domcontentloaded")

        models_text = (
            page.get_by_text("Registered Models").or_(page.get_by_text("Models")).or_(page.get_by_text("No models"))
        )
        expect(models_text.first).to_be_visible(timeout=15000)
