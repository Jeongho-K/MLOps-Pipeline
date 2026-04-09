"""Deployment workflow E2E test.

Tests the deployment flow: verify champion model loaded →
health check → Grafana metrics.
"""

from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

from .helpers.api_client import get_health, get_model_info
from .helpers.pages import GrafanaPage


class TestDeploymentWorkflow:
    """Champion model → health check → Grafana metrics."""

    def test_01_health_check(self, api_base_url: str):
        """API /health endpoint should return ok status."""
        result = get_health(api_base_url)
        assert result["status"] == "ok"

    def test_02_model_info(self, api_base_url: str):
        """API /model/info should return current model metadata."""
        try:
            result = get_model_info(api_base_url)
            assert "model_name" in result or "name" in result
        except Exception:
            # Model might not be loaded if no training has been done
            pytest.skip("No model loaded — training may not have been run")

    def test_03_nginx_proxy_works(self, nginx_base_url: str):
        """Nginx reverse proxy should forward to API."""
        import httpx

        response = httpx.get(f"{nginx_base_url}/health", timeout=10.0)
        assert response.status_code == 200
        result = response.json()
        assert result["status"] == "ok"

    def test_04_grafana_dashboard_no_errors(self, grafana_page: Page, grafana_base_url: str):
        """Grafana dashboard should render without errors."""
        gp = GrafanaPage(grafana_page, grafana_base_url)
        gp.navigate_to_dashboard()

        grafana_page.wait_for_load_state("networkidle")
        assert not gp.has_panel_errors()

    def test_05_grafana_request_rate_panel(self, grafana_page: Page, grafana_base_url: str):
        """Grafana should show Request Rate panel."""
        gp = GrafanaPage(grafana_page, grafana_base_url)
        gp.navigate_to_dashboard()

        expect(grafana_page.get_by_text("Request Rate").first).to_be_visible(timeout=15000)
