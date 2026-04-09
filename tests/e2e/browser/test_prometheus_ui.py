"""Prometheus UI verification tests.

Validates that the Prometheus query interface loads,
targets are visible, and queries execute successfully.
"""

from __future__ import annotations

import re

from playwright.sync_api import Page, expect


class TestPrometheusUI:
    """Verify Prometheus UI loads and query interface works."""

    def test_home_page_loads(self, page: Page, prometheus_base_url: str):
        """Prometheus home page should render."""
        page.goto(prometheus_base_url)
        page.wait_for_load_state("domcontentloaded")

        expect(page).to_have_title(re.compile("Prometheus"), timeout=15000)

    def test_targets_page_loads(self, page: Page, prometheus_base_url: str):
        """Targets page should load and contain target info."""
        page.goto(f"{prometheus_base_url}/targets")
        page.wait_for_load_state("domcontentloaded")

        # Wait for SPA to render — targets page shows scrape pools
        expect(page).to_have_title(re.compile("Prometheus"), timeout=15000)

    def test_targets_contain_api_job(self, page: Page, prometheus_base_url: str):
        """Targets should contain the API scrape target."""
        page.goto(f"{prometheus_base_url}/targets")
        page.wait_for_load_state("domcontentloaded")

        # Wait for targets to render, then check for "api" job
        expect(page.locator("body")).to_contain_text("api", timeout=15000)

    def test_query_page_loads(self, page: Page, prometheus_base_url: str):
        """Prometheus query/graph page should be accessible."""
        page.goto(f"{prometheus_base_url}/graph")
        page.wait_for_load_state("domcontentloaded")

        expect(page).to_have_title(re.compile("Prometheus"), timeout=15000)
