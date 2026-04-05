"""Shared fixtures for E2E tests.

E2E tests require all Docker services to be running (``make up``).
If services are unreachable, the entire test module is automatically skipped.
"""

from __future__ import annotations

import os
import urllib.error
import urllib.request

import boto3
import pytest


def _service_is_reachable(url: str, timeout: float = 3.0) -> bool:
    """Check if a URL responds within the timeout."""
    try:
        urllib.request.urlopen(url, timeout=timeout)
        return True
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Auto-mark every collected test in this package as e2e.

    Also skip the entire collection if core services are not reachable.
    """
    api_port = os.environ.get("API_PORT", "8000")
    api_url = f"http://localhost:{api_port}/health"

    services_up = _service_is_reachable(api_url)

    for item in items:
        if "e2e" in str(item.fspath):
            item.add_marker(pytest.mark.e2e)
            if not services_up:
                item.add_marker(pytest.mark.skip(reason="Docker services not running (make up)"))


# ---------------------------------------------------------------------------
# URL fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def api_base_url() -> str:
    """Return the base URL for the serving API."""
    port = os.environ.get("API_PORT", "8000")
    return f"http://localhost:{port}"


@pytest.fixture(scope="session")
def nginx_base_url() -> str:
    """Return the base URL for the Nginx reverse proxy."""
    port = os.environ.get("NGINX_PORT", "80")
    return f"http://localhost:{port}"


@pytest.fixture(scope="session")
def mlflow_base_url() -> str:
    """Return the base URL for the MLflow UI."""
    port = os.environ.get("MLFLOW_PORT", "5000")
    return f"http://localhost:{port}"


@pytest.fixture(scope="session")
def prefect_base_url() -> str:
    """Return the base URL for the Prefect server."""
    port = os.environ.get("PREFECT_PORT", "4200")
    return f"http://localhost:{port}"


@pytest.fixture(scope="session")
def prometheus_base_url() -> str:
    """Return the base URL for Prometheus."""
    port = os.environ.get("PROMETHEUS_PORT", "9090")
    return f"http://localhost:{port}"


@pytest.fixture(scope="session")
def grafana_base_url() -> str:
    """Return the base URL for Grafana."""
    port = os.environ.get("GRAFANA_PORT", "3000")
    return f"http://localhost:{port}"


@pytest.fixture(scope="session")
def pushgateway_base_url() -> str:
    """Return the base URL for the Pushgateway."""
    port = os.environ.get("PUSHGATEWAY_PORT", "9091")
    return f"http://localhost:{port}"


# ---------------------------------------------------------------------------
# Storage fixture
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def minio_s3_client():
    """Return a boto3 S3 client configured for the local MinIO instance."""
    endpoint_url = os.environ.get(
        "MLFLOW_S3_ENDPOINT_URL",
        f"http://localhost:{os.environ.get('MINIO_API_PORT', '9000')}",
    )
    access_key = os.environ.get("MINIO_ROOT_USER", "minioadmin")
    secret_key = os.environ.get("MINIO_ROOT_PASSWORD", "minioadmin123")

    return boto3.client(
        "s3",
        endpoint_url=endpoint_url,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name="us-east-1",
    )
