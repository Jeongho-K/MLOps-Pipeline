"""Unit tests for the canary deployment flow."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from src.core.orchestration.flows.deployment_flow import (
    _rollback,
    _run_canary_monitoring,
    deployment_flow,
)


class TestRunCanaryMonitoring:
    """Tests for the G4 monitoring loop."""

    @patch("src.core.orchestration.flows.deployment_flow.time.sleep")
    @patch("src.core.orchestration.flows.deployment_flow.check_canary_gate")
    def test_returns_true_when_all_checks_pass(self, mock_gate: MagicMock, _mock_sleep: MagicMock) -> None:
        mock_gate.return_value = {"passed": True, "reason": "ok", "metrics": {}}

        from src.core.orchestration.config_deployment import DeploymentConfig

        config = DeploymentConfig()
        result = _run_canary_monitoring(
            config=config,
            duration_minutes=1,
            interval_seconds=30,
            max_error_rate_ratio=1.5,
            max_latency_ratio=1.3,
            absolute_max_error_rate=0.05,
        )
        assert result is True
        # 60s / 30s = 2 checks
        assert mock_gate.call_count == 2

    @patch("src.core.orchestration.flows.deployment_flow.time.sleep")
    @patch("src.core.orchestration.flows.deployment_flow.check_canary_gate")
    def test_returns_false_on_first_failure(self, mock_gate: MagicMock, _mock_sleep: MagicMock) -> None:
        mock_gate.return_value = {"passed": False, "reason": "error rate high", "metrics": {}}

        from src.core.orchestration.config_deployment import DeploymentConfig

        config = DeploymentConfig()
        result = _run_canary_monitoring(
            config=config,
            duration_minutes=5,
            interval_seconds=60,
            max_error_rate_ratio=1.5,
            max_latency_ratio=1.3,
            absolute_max_error_rate=0.05,
        )
        assert result is False
        # Should stop after first failure
        assert mock_gate.call_count == 1


class TestRollback:
    """Tests for the rollback path."""

    @patch("src.core.orchestration.flows.deployment_flow.stop_canary_container")
    @patch("src.core.orchestration.flows.deployment_flow.update_nginx_weights")
    def test_rollback_restores_champion_only(self, mock_nginx: MagicMock, mock_stop: MagicMock) -> None:
        from src.core.orchestration.config_deployment import DeploymentConfig

        config = DeploymentConfig()
        result = _rollback(config)

        assert result["status"] == "rolled_back"
        mock_nginx.assert_called_once_with(
            champion_weight=10,
            canary_weight=0,
            nginx_container=config.nginx_container_name,
            upstream_path=config.nginx_upstream_path,
        )
        mock_stop.assert_called_once()


class TestDeploymentFlow:
    """Integration-level tests for the deployment flow."""

    @patch("src.core.orchestration.flows.deployment_flow._create_deployment_artifact")
    @patch("src.core.orchestration.flows.deployment_flow._run_canary_monitoring")
    @patch("src.core.orchestration.flows.deployment_flow.update_nginx_weights")
    @patch("src.core.orchestration.flows.deployment_flow.wait_for_canary_health")
    @patch("src.core.orchestration.flows.deployment_flow.start_canary_container")
    @patch("src.core.orchestration.flows.deployment_flow.reload_champion_model")
    @patch("src.core.orchestration.flows.deployment_flow.stop_canary_container")
    def test_happy_path_rolls_out(
        self,
        mock_stop: MagicMock,
        mock_reload: MagicMock,
        mock_start: MagicMock,
        mock_health: MagicMock,
        mock_nginx: MagicMock,
        mock_monitor: MagicMock,
        _mock_artifact: MagicMock,
    ) -> None:
        mock_monitor.return_value = True  # G4 passes

        result = deployment_flow.fn(trigger_source="test")

        assert result["status"] == "rolled_out"
        mock_start.assert_called_once()
        mock_health.assert_called_once()
        # nginx called twice: split traffic + full rollout
        assert mock_nginx.call_count == 2
        mock_reload.assert_called_once()
        mock_stop.assert_called_once()

    @patch("src.core.orchestration.flows.deployment_flow._create_deployment_artifact")
    @patch("src.core.orchestration.flows.deployment_flow._run_canary_monitoring")
    @patch("src.core.orchestration.flows.deployment_flow.update_nginx_weights")
    @patch("src.core.orchestration.flows.deployment_flow.wait_for_canary_health")
    @patch("src.core.orchestration.flows.deployment_flow.start_canary_container")
    @patch("src.core.orchestration.flows.deployment_flow.stop_canary_container")
    def test_failed_canary_rolls_back(
        self,
        mock_stop: MagicMock,
        mock_start: MagicMock,
        mock_health: MagicMock,
        mock_nginx: MagicMock,
        mock_monitor: MagicMock,
        _mock_artifact: MagicMock,
    ) -> None:
        mock_monitor.return_value = False  # G4 fails

        result = deployment_flow.fn(trigger_source="test")

        assert result["status"] == "rolled_back"
        mock_stop.assert_called_once()
