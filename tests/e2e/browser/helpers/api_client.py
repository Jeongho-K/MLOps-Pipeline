"""Thin httpx wrapper for API calls within Playwright E2E tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx


def predict_image(api_base_url: str, image_path: str | Path) -> dict[str, Any]:
    """Upload an image to the prediction endpoint and return the response.

    Args:
        api_base_url: Base URL for the serving API (e.g., http://localhost:8000).
        image_path: Path to the image file to upload.

    Returns:
        Parsed JSON response containing predicted_class, confidence, etc.
    """
    with open(image_path, "rb") as f:
        response = httpx.post(
            f"{api_base_url}/predict",
            files={"file": (Path(image_path).name, f, "image/png")},
            timeout=30.0,
        )
    response.raise_for_status()
    return response.json()


def get_model_info(api_base_url: str) -> dict[str, Any]:
    """Get current model info from the API.

    Args:
        api_base_url: Base URL for the serving API.

    Returns:
        Parsed JSON response with model name, version, etc.
    """
    response = httpx.get(f"{api_base_url}/model/info", timeout=10.0)
    response.raise_for_status()
    return response.json()


def get_health(api_base_url: str) -> dict[str, Any]:
    """Get health status from the API.

    Args:
        api_base_url: Base URL for the serving API.

    Returns:
        Parsed JSON response with status and model_loaded flag.
    """
    response = httpx.get(f"{api_base_url}/health", timeout=10.0)
    response.raise_for_status()
    return response.json()


def trigger_retraining(api_base_url: str) -> dict[str, Any]:
    """Trigger continuous training deployment.

    Args:
        api_base_url: Base URL for the serving API.

    Returns:
        Parsed JSON response with status and deployment info.
    """
    response = httpx.post(f"{api_base_url}/admin/trigger-retraining", timeout=15.0)
    response.raise_for_status()
    return response.json()


def query_prometheus(prometheus_base_url: str, query: str) -> dict[str, Any]:
    """Execute a PromQL instant query.

    Args:
        prometheus_base_url: Base URL for Prometheus.
        query: PromQL expression.

    Returns:
        Parsed JSON response from Prometheus API.
    """
    response = httpx.get(
        f"{prometheus_base_url}/api/v1/query",
        params={"query": query},
        timeout=10.0,
    )
    response.raise_for_status()
    return response.json()
