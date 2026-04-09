"""Playwright-specific fixtures for browser-based E2E tests.

Inherits all session-scoped URL fixtures from the parent ``tests/e2e/conftest.py``
via pytest's conftest hierarchy.
"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from playwright.sync_api import Browser, Page

# ---------------------------------------------------------------------------
# Browser launch configuration
# ---------------------------------------------------------------------------

SCREENSHOT_DIR = Path("test-results/screenshots")


@pytest.fixture(scope="session")
def browser_type_launch_args() -> dict:
    """Configure browser launch arguments — use system Chrome."""
    return {
        "channel": "chrome",
        "slow_mo": int(os.environ.get("PLAYWRIGHT_SLOW_MO", "0")),
    }


@pytest.fixture(scope="session")
def browser_context_args() -> dict:
    """Default context args applied to all browser contexts."""
    return {
        "viewport": {"width": 1280, "height": 720},
        "ignore_https_errors": True,
    }


# ---------------------------------------------------------------------------
# Service credentials
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def grafana_credentials() -> dict[str, str]:
    """Grafana admin credentials from environment."""
    return {
        "username": os.environ.get("GRAFANA_ADMIN_USER", "admin"),
        "password": os.environ.get("GRAFANA_ADMIN_PASSWORD", "admin"),
    }


@pytest.fixture(scope="session")
def minio_credentials() -> dict[str, str]:
    """MinIO console credentials from environment."""
    return {
        "username": os.environ.get("MINIO_ROOT_USER", "minioadmin"),
        "password": os.environ.get("MINIO_ROOT_PASSWORD", "minioadmin123"),
    }


@pytest.fixture(scope="session")
def label_studio_credentials() -> dict[str, str]:
    """Label Studio credentials from environment."""
    return {
        "email": os.environ.get("LABEL_STUDIO_USER", "admin@example.com"),
        "password": os.environ.get("LABEL_STUDIO_PASSWORD", "admin123"),
    }


# ---------------------------------------------------------------------------
# Session-scoped authenticated storage states
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def grafana_storage_state(
    browser: Browser,
    grafana_base_url: str,
    grafana_credentials: dict[str, str],
    tmp_path_factory: pytest.TempPathFactory,
) -> str:
    """Login to Grafana once and persist auth state for the session."""
    state_path = str(tmp_path_factory.mktemp("auth") / "grafana.json")
    context = browser.new_context()
    page = context.new_page()

    page.goto(f"{grafana_base_url}/login")
    page.fill("input[name='user']", grafana_credentials["username"])
    page.fill("input[name='password']", grafana_credentials["password"])
    page.click("button[type='submit']")
    page.wait_for_load_state("networkidle")

    # Handle first-login "change password" prompt
    skip_btn = page.get_by_text("Skip")
    if skip_btn.count() > 0:
        skip_btn.click()
        page.wait_for_load_state("networkidle")

    context.storage_state(path=state_path)
    context.close()
    return state_path


@pytest.fixture(scope="session")
def minio_storage_state(
    browser: Browser,
    minio_console_url: str,
    minio_credentials: dict[str, str],
    tmp_path_factory: pytest.TempPathFactory,
) -> str:
    """Login to MinIO Console once and persist auth state for the session."""
    state_path = str(tmp_path_factory.mktemp("auth") / "minio.json")
    context = browser.new_context()
    page = context.new_page()

    page.goto(f"{minio_console_url}/login")
    page.fill("#accessKey", minio_credentials["username"])
    page.fill("#secretKey", minio_credentials["password"])
    page.click("button[type='submit']")
    page.wait_for_load_state("networkidle")

    # MinIO may show a license agreement page after first login
    import time

    time.sleep(2)
    agree_btn = page.get_by_text("Agree")
    if agree_btn.count() > 0:
        agree_btn.click()
        page.wait_for_load_state("networkidle")

    context.storage_state(path=state_path)
    context.close()
    return state_path


@pytest.fixture(scope="session")
def label_studio_storage_state(
    browser: Browser,
    label_studio_base_url: str,
    label_studio_credentials: dict[str, str],
    tmp_path_factory: pytest.TempPathFactory,
) -> str:
    """Login or signup to Label Studio once and persist auth state."""
    state_path = str(tmp_path_factory.mktemp("auth") / "label_studio.json")
    context = browser.new_context()
    page = context.new_page()

    try:
        page.goto(f"{label_studio_base_url}/user/login", timeout=10000)
    except Exception:
        context.close()
        pytest.skip("Label Studio is not reachable")
    page.wait_for_load_state("domcontentloaded")

    # Label Studio shows signup form on first run, login form on subsequent runs
    if page.locator("input[name='email']").count() > 0 and page.url.endswith("/user/signup"):
        # First run — signup
        page.fill("input[name='email']", label_studio_credentials["email"])
        page.fill("input[name='password']", label_studio_credentials["password"])
        page.click("button[type='submit']")
    else:
        # Subsequent runs — login
        page.fill("input[name='email']", label_studio_credentials["email"])
        page.fill("input[name='password']", label_studio_credentials["password"])
        page.click("button[type='submit']")

    page.wait_for_url(f"{label_studio_base_url}/**", timeout=15000)

    context.storage_state(path=state_path)
    context.close()
    return state_path


# ---------------------------------------------------------------------------
# Authenticated page factories
# ---------------------------------------------------------------------------


@pytest.fixture
def grafana_page(browser: Browser, grafana_storage_state: str) -> Page:
    """Fresh page with Grafana auth pre-loaded."""
    context = browser.new_context(storage_state=grafana_storage_state)
    page = context.new_page()
    yield page
    context.close()


@pytest.fixture
def minio_page(browser: Browser, minio_storage_state: str) -> Page:
    """Fresh page with MinIO Console auth pre-loaded."""
    context = browser.new_context(storage_state=minio_storage_state)
    page = context.new_page()
    yield page
    context.close()


@pytest.fixture
def label_studio_page(browser: Browser, label_studio_storage_state: str) -> Page:
    """Fresh page with Label Studio auth pre-loaded."""
    context = browser.new_context(storage_state=label_studio_storage_state)
    page = context.new_page()
    yield page
    context.close()


# ---------------------------------------------------------------------------
# Screenshot on failure
# ---------------------------------------------------------------------------


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item: pytest.Item):
    """Capture screenshot on test failure."""
    outcome = yield
    report = outcome.get_result()

    if report.when == "call" and report.failed:
        page_fixtures = ("page", "grafana_page", "minio_page", "label_studio_page")
        page: Page | None = next(
            (item.funcargs.get(f) for f in page_fixtures if item.funcargs.get(f)),
            None,
        )
        if page and not page.is_closed():
            SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            name = f"{item.name}_{timestamp}.png"
            page.screenshot(path=str(SCREENSHOT_DIR / name))


# ---------------------------------------------------------------------------
# Auto-marking
# ---------------------------------------------------------------------------


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Add 'playwright' marker to all tests in this directory."""
    for item in items:
        if "browser" in str(item.fspath):
            item.add_marker(pytest.mark.playwright)
