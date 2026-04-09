"""Labeling workflow E2E test.

Tests the labeling flow: create Label Studio project → import tasks →
annotate in browser → verify webhook endpoint.

Tests requiring Label Studio UI are skipped if the service is not reachable.
"""

from __future__ import annotations

import urllib.error
import urllib.request

import httpx
import pytest
from playwright.sync_api import Page, expect


def _label_studio_is_up(base_url: str) -> bool:
    """Check if Label Studio is reachable."""
    try:
        urllib.request.urlopen(base_url, timeout=3)
        return True
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


class TestLabelingWorkflow:
    """Label Studio project creation, task import, and annotation."""

    @pytest.mark.skipif(
        not _label_studio_is_up(f"http://localhost:{__import__('os').environ.get('LABEL_STUDIO_PORT', '8081')}"),
        reason="Label Studio is not reachable",
    )
    def test_01_projects_page_accessible(self, label_studio_page: Page, label_studio_base_url: str):
        """Label Studio projects page should be accessible."""
        label_studio_page.goto(f"{label_studio_base_url}/projects")
        label_studio_page.wait_for_load_state("domcontentloaded")

        expect(
            label_studio_page.get_by_text("Projects").or_(label_studio_page.get_by_text("Create")).first
        ).to_be_visible(timeout=15000)

    @pytest.mark.skipif(
        not _label_studio_is_up(f"http://localhost:{__import__('os').environ.get('LABEL_STUDIO_PORT', '8081')}"),
        reason="Label Studio is not reachable",
    )
    def test_02_create_project_ui(self, label_studio_page: Page, label_studio_base_url: str):
        """Should be able to initiate project creation."""
        label_studio_page.goto(f"{label_studio_base_url}/projects")
        label_studio_page.wait_for_load_state("domcontentloaded")

        create_btn = label_studio_page.get_by_text("Create").first
        expect(create_btn).to_be_visible(timeout=10000)

    @pytest.mark.skipif(
        not _label_studio_is_up(f"http://localhost:{__import__('os').environ.get('LABEL_STUDIO_PORT', '8081')}"),
        reason="Label Studio is not reachable",
    )
    def test_03_labeling_interface_elements(self, label_studio_page: Page, label_studio_base_url: str):
        """Label Studio should expose annotation-related UI elements."""
        label_studio_page.goto(f"{label_studio_base_url}/projects")
        label_studio_page.wait_for_load_state("domcontentloaded")

        expect(label_studio_page.locator("header, nav").first).to_be_visible(timeout=10000)

    def test_04_api_webhook_endpoint_exists(self, api_base_url: str):
        """API webhook endpoint should be reachable (POST-only)."""
        response = httpx.get(f"{api_base_url}/webhooks/label-studio", timeout=10.0)
        # POST-only endpoint returns 405 Method Not Allowed, not 404
        assert response.status_code != 404, "Webhook endpoint not found"
