"""Unit tests for deployment tasks."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.orchestration.tasks.deployment_tasks import (
    start_canary_container,
    stop_canary_container,
    update_nginx_weights,
    wait_for_canary_health,
)


class TestStartCanaryContainer:
    """Tests for start_canary_container."""

    @patch("src.orchestration.tasks.deployment_tasks.subprocess.run")
    def test_calls_docker_compose_with_canary_profile(
        self, mock_run: MagicMock
    ) -> None:
        mock_run.return_value = MagicMock(returncode=0, stderr="")
        start_canary_container.fn(project_name="test-project")

        cmd = mock_run.call_args[0][0]
        assert "docker" in cmd
        assert "--profile" in cmd
        assert "canary" in cmd
        assert "api-canary" in cmd

    @patch("src.orchestration.tasks.deployment_tasks.subprocess.run")
    def test_raises_on_failure(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(returncode=1, stderr="error")
        with pytest.raises(RuntimeError, match="Failed to start canary"):
            start_canary_container.fn()


class TestWaitForCanaryHealth:
    """Tests for wait_for_canary_health."""

    @patch("src.orchestration.tasks.deployment_tasks.httpx.get")
    def test_returns_on_healthy_response(self, mock_get: MagicMock) -> None:
        mock_get.return_value = MagicMock(status_code=200)
        # Should not raise
        wait_for_canary_health.fn(
            health_url="http://canary:8000/health",
            timeout_seconds=5,
            poll_interval=0,
        )

    @patch("src.orchestration.tasks.deployment_tasks.time.sleep")
    @patch("src.orchestration.tasks.deployment_tasks.time.monotonic")
    @patch("src.orchestration.tasks.deployment_tasks.httpx.get")
    def test_raises_on_timeout(
        self, mock_get: MagicMock, mock_time: MagicMock, _mock_sleep: MagicMock
    ) -> None:
        import httpx

        mock_get.side_effect = httpx.ConnectError("refused")
        # Simulate time passing beyond timeout
        mock_time.side_effect = [0, 0, 200]

        with pytest.raises(TimeoutError, match="did not become healthy"):
            wait_for_canary_health.fn(timeout_seconds=10, poll_interval=1)


class TestUpdateNginxWeights:
    """Tests for update_nginx_weights."""

    @patch("src.orchestration.tasks.deployment_tasks._run_cmd")
    def test_generates_weighted_config(
        self, mock_cmd: MagicMock, tmp_path: Path
    ) -> None:
        template_content = (
            "upstream api_backend {{\n"
            "    server api:8000 weight={champion_weight};\n"
            "    server api-canary:8000 weight={canary_weight};\n"
            "}}\n"
        )
        with patch.object(
            Path, "read_text", return_value=template_content
        ):
            update_nginx_weights.fn(champion_weight=9, canary_weight=1)

        # Should have called docker cp and nginx reload
        assert mock_cmd.call_count == 2

    @patch("src.orchestration.tasks.deployment_tasks._run_cmd")
    def test_generates_default_config_when_canary_zero(
        self, mock_cmd: MagicMock
    ) -> None:
        update_nginx_weights.fn(champion_weight=10, canary_weight=0)

        # Verify the written config is default (no canary)
        assert mock_cmd.call_count == 2


class TestStopCanaryContainer:
    """Tests for stop_canary_container."""

    @patch("src.orchestration.tasks.deployment_tasks.subprocess.run")
    def test_calls_docker_compose_stop(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(returncode=0, stderr="")
        stop_canary_container.fn()

        cmd = mock_run.call_args[0][0]
        assert "stop" in cmd
        assert "api-canary" in cmd
