"""Unit tests for LabelStudioBridge REST API client."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest

from src.core.active_learning.labeling.bridge import LabelStudioBridge


@pytest.fixture
def bridge():
    b = LabelStudioBridge(
        base_url="http://label-studio:8080",
        api_key="test-token-abc123",
        project_id=1,
    )
    yield b
    b.close()


class TestLabelStudioBridge:
    def test_create_tasks_sends_post(self, bridge):
        samples = [{"image": "http://minio:9000/bucket/img1.jpg"}]
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 201
        mock_response.json.return_value = [{"id": 1}]
        mock_response.raise_for_status = MagicMock()

        with patch.object(bridge._client, "post", return_value=mock_response) as mock_post:
            result = bridge.create_tasks(samples)

        mock_post.assert_called_once_with("/api/projects/1/import", json=samples)
        assert result == [{"id": 1}]

    def test_create_tasks_with_samples(self, bridge):
        samples = [
            {
                "image": "http://minio:9000/bucket/img1.jpg",
                "predicted_class": "cat",
                "confidence": 0.42,
            },
            {
                "image": "http://minio:9000/bucket/img2.jpg",
                "predicted_class": "dog",
                "confidence": 0.38,
            },
        ]
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 201
        mock_response.json.return_value = [{"id": 1}, {"id": 2}]
        mock_response.raise_for_status = MagicMock()

        with patch.object(bridge._client, "post", return_value=mock_response) as mock_post:
            result = bridge.create_tasks(samples)

        _, kwargs = mock_post.call_args
        assert kwargs["json"] == samples
        assert len(result) == 2

    def test_create_tasks_empty_list_returns_early(self, bridge):
        with patch.object(bridge._client, "post") as mock_post:
            result = bridge.create_tasks([])

        mock_post.assert_not_called()
        assert result == []

    def test_get_completed_annotations(self, bridge):
        annotations = [
            {"id": 1, "annotations": [{"result": [{"value": {"choices": ["cat"]}}]}]},
            {"id": 2, "annotations": [{"result": [{"value": {"choices": ["dog"]}}]}]},
        ]
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = annotations
        mock_response.raise_for_status = MagicMock()

        with patch.object(bridge._client, "get", return_value=mock_response) as mock_get:
            result = bridge.get_completed_annotations()

        mock_get.assert_called_once_with("/api/projects/1/export", params={"exportType": "JSON"})
        assert len(result) == 2

    def test_get_completed_annotations_custom_project(self, bridge):
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = []
        mock_response.raise_for_status = MagicMock()

        with patch.object(bridge._client, "get", return_value=mock_response) as mock_get:
            bridge.get_completed_annotations(project_id=42)

        mock_get.assert_called_once_with("/api/projects/42/export", params={"exportType": "JSON"})

    def test_get_project_stats(self, bridge):
        project_data = {
            "id": 1,
            "title": "CV Classification",
            "task_number": 100,
            "num_tasks_with_annotations": 45,
            "total_annotations_number": 50,
            "total_predictions_number": 100,
        }
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = project_data
        mock_response.raise_for_status = MagicMock()

        with patch.object(bridge._client, "get", return_value=mock_response) as mock_get:
            stats = bridge.get_project_stats()

        mock_get.assert_called_once_with("/api/projects/1/")
        assert stats["task_number"] == 100
        assert stats["num_tasks_with_annotations"] == 45
        assert stats["title"] == "CV Classification"

    def test_auth_header_included(self, bridge):
        assert bridge._client.headers["Authorization"] == "Token test-token-abc123"

    def test_handles_api_error(self, bridge):
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 500
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Server Error",
            request=MagicMock(spec=httpx.Request),
            response=mock_response,
        )

        with patch.object(bridge._client, "post", return_value=mock_response), pytest.raises(httpx.HTTPStatusError):
            bridge.create_tasks([{"image": "http://example.com/img.jpg"}])

    def test_handles_export_api_error(self, bridge):
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 404
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Not Found",
            request=MagicMock(spec=httpx.Request),
            response=mock_response,
        )

        with patch.object(bridge._client, "get", return_value=mock_response), pytest.raises(httpx.HTTPStatusError):
            bridge.get_completed_annotations()

    def test_close_closes_client(self, bridge):
        with patch.object(bridge._client, "close") as mock_close:
            bridge.close()
        mock_close.assert_called_once()

    def test_base_url_trailing_slash_stripped(self):
        b = LabelStudioBridge(
            base_url="http://label-studio:8080/",
            api_key="key",
            project_id=1,
        )
        assert b._base_url == "http://label-studio:8080"
        b.close()
