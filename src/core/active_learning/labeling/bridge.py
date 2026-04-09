"""REST API client for Label Studio integration.

Uses httpx for HTTP communication. Does NOT depend on the label-studio-sdk.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class LabelStudioBridge:
    """REST API client for Label Studio integration.

    Provides methods to create labeling tasks, export completed annotations,
    and retrieve project statistics via the Label Studio REST API.

    Args:
        base_url: Label Studio server base URL (e.g. ``http://label-studio:8080``).
        api_key: Label Studio API token for authentication.
        project_id: Default Label Studio project ID to operate on.
    """

    def __init__(self, base_url: str, api_key: str, project_id: int) -> None:
        self._base_url = base_url.rstrip("/")
        self._project_id = project_id
        self._client = httpx.Client(
            base_url=self._base_url,
            headers={"Authorization": f"Token {api_key}"},
            timeout=30.0,
        )

    def create_tasks(self, samples: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Import labeling tasks into the project.

        Args:
            samples: List of dicts with at minimum an ``image`` key (URL to image).
                Can also include ``predicted_class``, ``confidence`` for
                pre-annotation context.

        Returns:
            API response with imported task information.

        Raises:
            httpx.HTTPStatusError: If the API returns a non-2xx status.
        """
        if not samples:
            logger.warning("create_tasks called with empty samples list")
            return []

        url = f"/api/projects/{self._project_id}/import"
        logger.info("Importing %d tasks to project %d", len(samples), self._project_id)

        try:
            response = self._client.post(url, json=samples)
            response.raise_for_status()
            result = response.json()
            logger.info("Successfully imported tasks to project %d", self._project_id)
            return result
        except httpx.HTTPStatusError:
            logger.exception(
                "Label Studio API error importing tasks to project %d",
                self._project_id,
            )
            raise

    def get_completed_annotations(self, project_id: int | None = None) -> list[dict[str, Any]]:
        """Export completed annotations from the project.

        Args:
            project_id: Project ID to export from. Defaults to the configured project.

        Returns:
            List of task dicts with their annotations.

        Raises:
            httpx.HTTPStatusError: If the API returns a non-2xx status.
        """
        pid = project_id or self._project_id
        url = f"/api/projects/{pid}/export"
        logger.info("Exporting annotations from project %d", pid)

        try:
            response = self._client.get(url, params={"exportType": "JSON"})
            response.raise_for_status()
            result = response.json()
            logger.info("Exported %d annotated tasks from project %d", len(result), pid)
            return result
        except httpx.HTTPStatusError:
            logger.exception(
                "Label Studio API error exporting annotations from project %d",
                pid,
            )
            raise

    def get_project_stats(self, project_id: int | None = None) -> dict[str, Any]:
        """Get project statistics.

        Args:
            project_id: Project ID to query. Defaults to the configured project.

        Returns:
            Dict with project info including task counts
            (``task_number``, ``num_tasks_with_annotations``, etc.).

        Raises:
            httpx.HTTPStatusError: If the API returns a non-2xx status.
        """
        pid = project_id or self._project_id
        url = f"/api/projects/{pid}/"
        logger.info("Fetching stats for project %d", pid)

        try:
            response = self._client.get(url)
            response.raise_for_status()
            data = response.json()
            stats = {
                "id": data.get("id"),
                "title": data.get("title"),
                "task_number": data.get("task_number", 0),
                "num_tasks_with_annotations": data.get("num_tasks_with_annotations", 0),
                "total_annotations_number": data.get("total_annotations_number", 0),
                "total_predictions_number": data.get("total_predictions_number", 0),
            }
            logger.info(
                "Project %d: %d tasks, %d annotated",
                pid,
                stats["task_number"],
                stats["num_tasks_with_annotations"],
            )
            return stats
        except httpx.HTTPStatusError:
            logger.exception(
                "Label Studio API error fetching stats for project %d",
                pid,
            )
            raise

    def register_webhook(
        self,
        callback_url: str,
        events: list[str] | None = None,
    ) -> dict[str, Any] | None:
        """Register a webhook with Label Studio, skipping if already registered.

        Args:
            callback_url: URL that Label Studio will POST events to.
            events: Event types to subscribe to. Defaults to ANNOTATION_CREATED.

        Returns:
            Webhook registration response, or existing webhook if already registered.
            None if registration failed.
        """
        events = events or ["ANNOTATION_CREATED"]

        try:
            existing = self._client.get("/api/webhooks/").json()
            for wh in existing:
                if wh.get("url") == callback_url:
                    logger.info(
                        "Webhook already registered for %s (id=%s)",
                        callback_url,
                        wh.get("id"),
                    )
                    return wh
        except Exception:
            logger.warning("Failed to list existing webhooks", exc_info=True)

        payload: dict[str, Any] = {
            "project": self._project_id,
            "url": callback_url,
            "send_payload": True,
            "send_for_all_actions": False,
            "is_active": True,
            "actions": events,
        }

        try:
            response = self._client.post("/api/webhooks/", json=payload)
            response.raise_for_status()
            result = response.json()
            logger.info(
                "Registered Label Studio webhook: url=%s, project=%d, events=%s",
                callback_url,
                self._project_id,
                events,
            )
            return result
        except (httpx.HTTPStatusError, httpx.TransportError):
            logger.warning(
                "Failed to register webhook with Label Studio at %s",
                callback_url,
                exc_info=True,
            )
            return None

    def get_annotation_count(self, project_id: int | None = None) -> int:
        """Get the number of tasks with completed annotations.

        Args:
            project_id: Project ID to query. Defaults to the configured project.

        Returns:
            Number of tasks with at least one annotation.
        """
        stats = self.get_project_stats(project_id)
        return stats.get("num_tasks_with_annotations", 0)

    def close(self) -> None:
        """Close the HTTP client."""
        self._client.close()
        logger.debug("Label Studio bridge HTTP client closed")
