"""Integration tests for Label Studio connectivity.

Requires Label Studio Docker container running (docker compose up label-studio).
"""

from __future__ import annotations

import os
import uuid

import httpx
import pytest

LABEL_STUDIO_URL = os.environ.get("LABEL_STUDIO_URL", "http://localhost:8081")
LABEL_STUDIO_API_KEY = os.environ.get("LABEL_STUDIO_API_KEY", "")


def _label_studio_is_running() -> bool:
    """Check if Label Studio is reachable."""
    try:
        response = httpx.get(f"{LABEL_STUDIO_URL}/health", timeout=3)
        return response.status_code == 200
    except (httpx.ConnectError, httpx.TimeoutException):
        return False


skip_if_not_running = pytest.mark.skipif(
    not _label_studio_is_running(),
    reason="Label Studio is not running (start with: docker compose up label-studio)",
)


@skip_if_not_running
class TestLabelStudioIntegration:
    """Integration tests for Label Studio API."""

    def test_label_studio_health(self):
        """GET /health must return HTTP 200."""
        response = httpx.get(f"{LABEL_STUDIO_URL}/health", timeout=5)
        assert response.status_code == 200

    def test_label_studio_api_accessible(self):
        """GET /api/projects/ with auth token must return HTTP 200."""
        headers = {"Authorization": f"Token {LABEL_STUDIO_API_KEY}"}
        response = httpx.get(f"{LABEL_STUDIO_URL}/api/projects/", headers=headers, timeout=5)
        assert response.status_code == 200

    def test_create_and_list_project(self):
        """POST /api/projects/ creates a project, then GET verifies it exists."""
        headers = {
            "Authorization": f"Token {LABEL_STUDIO_API_KEY}",
            "Content-Type": "application/json",
        }
        project_title = f"test-project-{uuid.uuid4().hex[:8]}"

        # Create project
        create_response = httpx.post(
            f"{LABEL_STUDIO_URL}/api/projects/",
            headers=headers,
            json={
                "title": project_title,
                "label_config": '<View><Image name="image" value="$image"/></View>',
            },
            timeout=10,
        )
        assert create_response.status_code in (200, 201)

        project_id = create_response.json()["id"]

        # Verify project appears in list
        list_response = httpx.get(
            f"{LABEL_STUDIO_URL}/api/projects/",
            headers=headers,
            timeout=5,
        )
        assert list_response.status_code == 200

        project_ids = [p["id"] for p in list_response.json().get("results", list_response.json())]
        assert project_id in project_ids

        # Cleanup: delete the test project
        httpx.delete(
            f"{LABEL_STUDIO_URL}/api/projects/{project_id}/",
            headers=headers,
            timeout=5,
        )
