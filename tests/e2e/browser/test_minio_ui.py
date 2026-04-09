"""MinIO Console UI verification tests.

Validates that the MinIO Console loads, login works,
and bucket browsing is functional.
"""

from __future__ import annotations

from playwright.sync_api import Page, expect

from .helpers.pages import MinIOConsolePage

EXPECTED_BUCKETS = [
    "mlflow-artifacts",
    "dvc-storage",
    "model-registry",
    "prediction-logs",
    "drift-reports",
]


class TestMinIOUI:
    """Verify MinIO Console loads and bucket browsing works."""

    def test_login_page_renders(self, page: Page, minio_console_url: str):
        """MinIO Console login page should display credentials fields."""
        page.goto(f"{minio_console_url}/login")
        expect(page.locator("#accessKey")).to_be_visible(timeout=15000)
        expect(page.locator("#secretKey")).to_be_visible(timeout=15000)

    def test_login_succeeds(self, page: Page, minio_console_url: str, minio_credentials: dict):
        """Admin should be able to log in to MinIO Console."""
        mp = MinIOConsolePage(page, minio_console_url)
        mp.login(minio_credentials["username"], minio_credentials["password"])

        # Should be redirected to dashboard
        expect(page).not_to_have_url(f"{minio_console_url}/login")

    def test_buckets_listed(self, minio_page: Page, minio_console_url: str):
        """All expected buckets should appear in the bucket list."""
        mp = MinIOConsolePage(minio_page, minio_console_url)
        mp.navigate_to_buckets()

        for bucket_name in EXPECTED_BUCKETS:
            expect(minio_page.get_by_text(bucket_name).first).to_be_visible(timeout=10000)

    def test_object_browser_navigable(self, minio_page: Page, minio_console_url: str):
        """Should be able to navigate into a bucket via direct URL."""
        # Navigate directly to the bucket browser to avoid modal overlays
        minio_page.goto(f"{minio_console_url}/browser/{EXPECTED_BUCKETS[0]}")
        minio_page.wait_for_load_state("domcontentloaded")

        import re

        expect(minio_page).to_have_url(re.compile(rf"browser/{EXPECTED_BUCKETS[0]}"), timeout=10000)
