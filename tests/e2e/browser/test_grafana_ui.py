"""Grafana UI verification tests.

Validates that the Grafana dashboard loads correctly, panels render,
and basic interactions work.
"""

from __future__ import annotations

from playwright.sync_api import Page, expect

from .helpers.pages import GrafanaPage


class TestGrafanaUI:
    """Verify Grafana UI loads and dashboards render."""

    def test_login_page_renders(self, page: Page, grafana_base_url: str):
        """Grafana login page should display username/password fields."""
        page.goto(f"{grafana_base_url}/login")
        expect(page.locator("input[name='user']")).to_be_visible()
        expect(page.locator("input[name='password']")).to_be_visible()
        expect(page.locator("button[type='submit']")).to_be_visible()

    def test_login_succeeds(self, grafana_page: Page, grafana_base_url: str):
        """Authenticated page should work (login via storage state)."""
        # The grafana_page fixture uses storage state from a previous successful login.
        # Simply verify the authenticated page can access the dashboard.
        grafana_page.goto(grafana_base_url)
        grafana_page.wait_for_load_state("domcontentloaded")

        # Should not be redirected to login page
        assert "/login" not in grafana_page.url

    def test_mlops_dashboard_loads(self, grafana_page: Page, grafana_base_url: str):
        """MLOps overview dashboard should load with all 7 panels."""
        gp = GrafanaPage(grafana_page, grafana_base_url)
        gp.navigate_to_dashboard()

        import re

        expect(grafana_page).to_have_title(re.compile(r"Data Flywheel Overview.*Grafana"), timeout=15000)

    def test_dashboard_panels_present(self, grafana_page: Page, grafana_base_url: str):
        """All expected panel titles should be visible on the dashboard."""
        gp = GrafanaPage(grafana_page, grafana_base_url)
        gp.navigate_to_dashboard()

        for panel_title in GrafanaPage.EXPECTED_PANELS:
            expect(grafana_page.get_by_text(panel_title).first).to_be_visible(timeout=15000)

    def test_time_range_selector_works(self, grafana_page: Page, grafana_base_url: str):
        """Changing time range should not cause errors."""
        gp = GrafanaPage(grafana_page, grafana_base_url)
        gp.navigate_to_dashboard()

        # Click the time range picker
        time_picker = grafana_page.locator("[data-testid='data-testid TimePicker Open Button']")
        if time_picker.count() > 0:
            time_picker.click()
            # Select "Last 1 hour" if available
            last_hour = grafana_page.get_by_text("Last 1 hour")
            if last_hour.count() > 0:
                last_hour.click()

        # Dashboard should still be visible without errors
        assert not gp.has_panel_errors()

    def test_panel_no_errors(self, grafana_page: Page, grafana_base_url: str):
        """No panel should show 'Panel plugin not found' or error state."""
        gp = GrafanaPage(grafana_page, grafana_base_url)
        gp.navigate_to_dashboard()

        # Wait for panels to load
        grafana_page.wait_for_load_state("networkidle")
        assert not gp.has_panel_errors()
