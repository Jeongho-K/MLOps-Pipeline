"""Prefect UI verification tests.

Validates that the Prefect orchestration dashboard loads and
key pages are accessible.
"""

from __future__ import annotations

from playwright.sync_api import Page, expect


class TestPrefectUI:
    """Verify Prefect UI loads and displays flow information."""

    def test_dashboard_loads(self, page: Page, prefect_base_url: str):
        """Prefect dashboard should render with navigation."""
        page.goto(prefect_base_url)
        page.wait_for_load_state("domcontentloaded")

        # Prefect UI should show navigation elements
        expect(page.locator("nav, [class*='navigation'], [class*='sidebar']").first).to_be_visible(timeout=15000)

    def test_flow_runs_page_accessible(self, page: Page, prefect_base_url: str):
        """Flow runs list should be accessible."""
        page.goto(f"{prefect_base_url}/flow-runs")
        page.wait_for_load_state("domcontentloaded")

        # Prefect 3.x UI — verify page loads
        expect(page.locator("body")).to_contain_text("Flow", timeout=15000)

    def test_deployments_page_accessible(self, page: Page, prefect_base_url: str):
        """Deployments page should be accessible."""
        page.goto(f"{prefect_base_url}/deployments")
        page.wait_for_load_state("domcontentloaded")

        expect(page.locator("body")).to_contain_text("Deployment", timeout=15000)
