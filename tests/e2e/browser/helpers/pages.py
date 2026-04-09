"""Page Object wrappers for each service UI."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.sync_api import Page

# ---------------------------------------------------------------------------
# Grafana
# ---------------------------------------------------------------------------


class GrafanaPage:
    """Page Object for Grafana interactions."""

    DASHBOARD_UID = "mlops-overview"
    EXPECTED_PANELS = [
        "Request Rate",
        "Latency (p50 / p95 / p99)",
        "Error Rate (5xx)",
        "Prediction Class Distribution",
        "Prediction Confidence Distribution",
        "Drift Score",
        "Drift Status",
    ]

    def __init__(self, page: Page, base_url: str) -> None:
        self.page = page
        self.base_url = base_url

    def login(self, username: str, password: str) -> None:
        """Login to Grafana with credentials.

        Handles the first-login "change password" prompt by skipping it.
        """
        self.page.goto(f"{self.base_url}/login")
        self.page.fill("input[name='user']", username)
        self.page.fill("input[name='password']", password)
        self.page.click("button[type='submit']")
        self.page.wait_for_load_state("domcontentloaded")

        # Grafana may show "change password" prompt on first login with default creds
        skip_btn = self.page.get_by_text("Skip")
        if skip_btn.count() > 0:
            skip_btn.click()
            self.page.wait_for_load_state("domcontentloaded")

    def navigate_to_dashboard(self) -> None:
        """Navigate to the MLOps overview dashboard."""
        self.page.goto(f"{self.base_url}/d/{self.DASHBOARD_UID}")
        self.page.wait_for_load_state("domcontentloaded")

    def get_panel_titles(self) -> list[str]:
        """Extract all visible panel titles from the dashboard."""
        self.page.wait_for_selector("[data-testid='data-testid Panel header']", timeout=15000)
        elements = self.page.locator("[data-testid='data-testid Panel header'] h2").all()
        return [el.text_content().strip() for el in elements if el.text_content()]

    def has_panel_errors(self) -> bool:
        """Check if any panel shows an error state."""
        error_panels = self.page.locator("[data-testid='data-testid Panel status error']")
        return error_panels.count() > 0


# ---------------------------------------------------------------------------
# MLflow
# ---------------------------------------------------------------------------


class MLflowPage:
    """Page Object for MLflow UI interactions."""

    def __init__(self, page: Page, base_url: str) -> None:
        self.page = page
        self.base_url = base_url

    def navigate_to_experiments(self) -> None:
        """Navigate to the experiments list."""
        self.page.goto(self.base_url)
        self.page.wait_for_load_state("domcontentloaded")

    def navigate_to_model_registry(self) -> None:
        """Navigate to the model registry."""
        self.page.goto(f"{self.base_url}/#/models")
        self.page.wait_for_load_state("domcontentloaded")

    def get_experiment_names(self) -> list[str]:
        """Get list of experiment names from the sidebar."""
        self.page.wait_for_selector("[class*='experiment-name']", timeout=10000)
        elements = self.page.locator("[class*='experiment-name']").all()
        return [el.text_content().strip() for el in elements if el.text_content()]


# ---------------------------------------------------------------------------
# Label Studio
# ---------------------------------------------------------------------------


class LabelStudioPage:
    """Page Object for Label Studio UI interactions."""

    def __init__(self, page: Page, base_url: str) -> None:
        self.page = page
        self.base_url = base_url

    def login_or_signup(self, email: str, password: str) -> None:
        """Handle both first-run signup and subsequent login."""
        self.page.goto(f"{self.base_url}/user/login")
        self.page.wait_for_load_state("domcontentloaded")

        if self.page.url.endswith("/user/signup"):
            self.page.fill("input[name='email']", email)
            self.page.fill("input[name='password']", password)
            self.page.click("button[type='submit']")
        else:
            self.page.fill("input[name='email']", email)
            self.page.fill("input[name='password']", password)
            self.page.click("button[type='submit']")

        self.page.wait_for_url(f"{self.base_url}/**", timeout=15000)

    def navigate_to_projects(self) -> None:
        """Navigate to the projects page."""
        self.page.goto(f"{self.base_url}/projects")
        self.page.wait_for_load_state("domcontentloaded")

    def create_project(self, name: str) -> None:
        """Create a new labeling project."""
        self.navigate_to_projects()
        self.page.click("button:has-text('Create')")
        self.page.fill("input[name='title']", name)
        self.page.click("button:has-text('Save')")
        self.page.wait_for_load_state("domcontentloaded")


# ---------------------------------------------------------------------------
# Prefect
# ---------------------------------------------------------------------------


class PrefectPage:
    """Page Object for Prefect UI interactions."""

    def __init__(self, page: Page, base_url: str) -> None:
        self.page = page
        self.base_url = base_url

    def navigate_to_dashboard(self) -> None:
        """Navigate to Prefect dashboard."""
        self.page.goto(self.base_url)
        self.page.wait_for_load_state("domcontentloaded")

    def navigate_to_flow_runs(self) -> None:
        """Navigate to flow runs page."""
        self.page.goto(f"{self.base_url}/flow-runs")
        self.page.wait_for_load_state("domcontentloaded")

    def navigate_to_deployments(self) -> None:
        """Navigate to deployments page."""
        self.page.goto(f"{self.base_url}/deployments")
        self.page.wait_for_load_state("domcontentloaded")


# ---------------------------------------------------------------------------
# MinIO Console
# ---------------------------------------------------------------------------


class MinIOConsolePage:
    """Page Object for MinIO Console interactions."""

    def __init__(self, page: Page, base_url: str) -> None:
        self.page = page
        self.base_url = base_url

    def login(self, username: str, password: str) -> None:
        """Login to MinIO Console, handling license agreement if shown."""
        self.page.goto(f"{self.base_url}/login")
        self.page.fill("#accessKey", username)
        self.page.fill("#secretKey", password)
        self.page.click("button[type='submit']")
        self.page.wait_for_load_state("domcontentloaded")

        # Handle license agreement page on first login
        import time

        time.sleep(1)
        agree_btn = self.page.get_by_text("Agree")
        if agree_btn.count() > 0:
            agree_btn.click()
            self.page.wait_for_load_state("domcontentloaded")

    def navigate_to_buckets(self) -> None:
        """Navigate to the buckets page."""
        self.page.goto(f"{self.base_url}/buckets")
        self.page.wait_for_load_state("domcontentloaded")

    def get_bucket_names(self) -> list[str]:
        """Get list of bucket names from the buckets page."""
        self.navigate_to_buckets()
        self.page.wait_for_selector("table tbody tr", timeout=10000)
        rows = self.page.locator("table tbody tr").all()
        return [
            row.locator("td").first.text_content().strip() for row in rows if row.locator("td").first.text_content()
        ]


# ---------------------------------------------------------------------------
# Prometheus
# ---------------------------------------------------------------------------


class PrometheusPage:
    """Page Object for Prometheus UI interactions."""

    def __init__(self, page: Page, base_url: str) -> None:
        self.page = page
        self.base_url = base_url

    def navigate_to_graph(self) -> None:
        """Navigate to Prometheus graph/query page."""
        self.page.goto(f"{self.base_url}/graph")
        self.page.wait_for_load_state("domcontentloaded")

    def navigate_to_targets(self) -> None:
        """Navigate to Prometheus targets page."""
        self.page.goto(f"{self.base_url}/targets")
        self.page.wait_for_load_state("domcontentloaded")

    def execute_query(self, expression: str) -> None:
        """Type and execute a PromQL query."""
        self.navigate_to_graph()
        query_input = self.page.locator("textarea.cm-content, input[id='expr']").first
        query_input.fill(expression)
        self.page.click("button:has-text('Execute')")
        self.page.wait_for_load_state("domcontentloaded")
