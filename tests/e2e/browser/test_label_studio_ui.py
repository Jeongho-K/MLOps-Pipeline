"""Label Studio UI verification tests.

Validates that Label Studio loads, project management works,
and the annotation interface is accessible.

Note: Label Studio requires a properly initialized PostgreSQL database.
Tests are skipped if the service is not reachable.
"""

from __future__ import annotations

import urllib.error
import urllib.request

import pytest
from playwright.sync_api import Page, expect

from .helpers.pages import LabelStudioPage


def _label_studio_is_up(base_url: str) -> bool:
    """Check if Label Studio is reachable."""
    try:
        urllib.request.urlopen(base_url, timeout=3)
        return True
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


@pytest.mark.skipif(
    not _label_studio_is_up(f"http://localhost:{__import__('os').environ.get('LABEL_STUDIO_PORT', '8081')}"),
    reason="Label Studio is not reachable",
)
class TestLabelStudioUI:
    """Verify Label Studio UI loads and project management works."""

    def test_login_or_signup(
        self,
        page: Page,
        label_studio_base_url: str,
        label_studio_credentials: dict,
    ):
        """Admin should be able to login or signup on first run."""
        ls = LabelStudioPage(page, label_studio_base_url)
        ls.login_or_signup(
            label_studio_credentials["email"],
            label_studio_credentials["password"],
        )
        expect(page).not_to_have_url(f"{label_studio_base_url}/user/login")

    def test_projects_page_loads(self, label_studio_page: Page, label_studio_base_url: str):
        """Projects list page should render."""
        label_studio_page.goto(f"{label_studio_base_url}/projects")
        label_studio_page.wait_for_load_state("domcontentloaded")

        expect(
            label_studio_page.get_by_text("Projects").or_(label_studio_page.get_by_text("Create")).first
        ).to_be_visible(timeout=15000)

    def test_create_project_button_visible(self, label_studio_page: Page, label_studio_base_url: str):
        """Create project button should be accessible."""
        label_studio_page.goto(f"{label_studio_base_url}/projects")
        label_studio_page.wait_for_load_state("domcontentloaded")

        create_btn = label_studio_page.get_by_text("Create").first
        expect(create_btn).to_be_visible(timeout=10000)
