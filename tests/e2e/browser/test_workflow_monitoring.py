"""Monitoring workflow E2E test.

Tests the monitoring flow: Prometheus targets UP → Grafana panels render →
drift panels present.
"""

from __future__ import annotations

from playwright.sync_api import Page, expect

from .helpers.api_client import query_prometheus
from .helpers.pages import GrafanaPage


class TestMonitoringWorkflow:
    """Prometheus metrics → Grafana dashboard → drift monitoring."""

    def test_01_prometheus_targets_up(self, page: Page, prometheus_base_url: str):
        """Prometheus targets page should show API target."""
        page.goto(f"{prometheus_base_url}/targets")
        page.wait_for_load_state("domcontentloaded")

        expect(page.locator("body")).to_contain_text("api", timeout=15000)

    def test_02_prometheus_up_query(self, prometheus_base_url: str):
        """PromQL 'up' query should return results via API."""
        result = query_prometheus(prometheus_base_url, "up")
        assert result["status"] == "success"
        assert len(result["data"]["result"]) > 0

    def test_03_grafana_all_panels_render(self, grafana_page: Page, grafana_base_url: str):
        """All Grafana dashboard panels should render without error."""
        gp = GrafanaPage(grafana_page, grafana_base_url)
        gp.navigate_to_dashboard()

        # Verify all expected panels are visible
        for panel_title in GrafanaPage.EXPECTED_PANELS:
            expect(grafana_page.get_by_text(panel_title).first).to_be_visible(timeout=15000)

        # No panel errors
        assert not gp.has_panel_errors()

    def test_04_drift_panels_present(self, grafana_page: Page, grafana_base_url: str):
        """Drift Score and Drift Status panels should be present."""
        gp = GrafanaPage(grafana_page, grafana_base_url)
        gp.navigate_to_dashboard()

        expect(grafana_page.get_by_text("Drift Score").first).to_be_visible(timeout=15000)
        expect(grafana_page.get_by_text("Drift Status").first).to_be_visible(timeout=15000)

    def test_05_latency_panel_present(self, grafana_page: Page, grafana_base_url: str):
        """Latency panel should show p50/p95/p99 metrics."""
        gp = GrafanaPage(grafana_page, grafana_base_url)
        gp.navigate_to_dashboard()

        expect(grafana_page.get_by_text("Latency (p50 / p95 / p99)").first).to_be_visible(timeout=15000)
