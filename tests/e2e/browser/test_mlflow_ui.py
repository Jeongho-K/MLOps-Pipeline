"""MLflow UI verification tests.

Validates that the MLflow experiment tracking UI and model registry load correctly.
"""

from __future__ import annotations

from playwright.sync_api import Page, expect


class TestMLflowUI:
    """Verify MLflow UI loads and displays experiments."""

    def test_experiments_page_loads(self, page: Page, mlflow_base_url: str):
        """MLflow home page should render with experiments."""
        page.goto(mlflow_base_url)
        page.wait_for_load_state("domcontentloaded")

        # MLflow 3.x shows "Welcome to MLflow" on home page
        expect(page.get_by_text("Welcome to MLflow").first).to_be_visible(timeout=15000)

    def test_recent_experiments_visible(self, page: Page, mlflow_base_url: str):
        """MLflow should show Recent Experiments section."""
        page.goto(mlflow_base_url)
        page.wait_for_load_state("domcontentloaded")

        expect(page.get_by_text("Recent Experiments").or_(page.get_by_text("Experiments")).first).to_be_visible(
            timeout=15000
        )

    def test_model_registry_accessible(self, page: Page, mlflow_base_url: str):
        """MLflow model registry page should be accessible."""
        page.goto(f"{mlflow_base_url}/#/models")
        page.wait_for_load_state("domcontentloaded")

        # Should show model registry page
        expect(
            page.get_by_text("Registered Models")
            .or_(page.get_by_text("Models"))
            .or_(page.get_by_text("No models"))
            .first
        ).to_be_visible(timeout=15000)

    def test_default_experiment_exists(self, page: Page, mlflow_base_url: str):
        """Default experiment should be present."""
        page.goto(mlflow_base_url)
        page.wait_for_load_state("domcontentloaded")

        expect(page.get_by_text("Default").first).to_be_visible(timeout=15000)
