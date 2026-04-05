"""Unit tests for deployment configuration."""

from src.core.orchestration.config_deployment import DeploymentConfig


class TestDeploymentConfig:
    """Tests for DeploymentConfig defaults and overrides."""

    def test_default_values(self) -> None:
        """Default config should have expected values."""
        config = DeploymentConfig()
        assert config.canary_duration_minutes == 30
        assert config.canary_check_interval_seconds == 120
        assert config.canary_weight == 1
        assert config.champion_weight == 9
        assert config.max_error_rate_ratio == 1.5
        assert config.max_latency_ratio == 1.3
        assert config.absolute_max_error_rate == 0.05
        assert config.prometheus_url == "http://prometheus:9090"
        assert config.docker_compose_project == "data-flywheel"
        assert config.registered_model_name == "cv-classifier"
        assert config.mlflow_tracking_uri == "http://mlflow:5000"

    def test_override_values(self) -> None:
        """Config should accept overrides."""
        config = DeploymentConfig(
            canary_duration_minutes=60,
            canary_weight=2,
            champion_weight=8,
            max_error_rate_ratio=2.0,
            prometheus_url="http://localhost:9090",
        )
        assert config.canary_duration_minutes == 60
        assert config.canary_weight == 2
        assert config.champion_weight == 8
        assert config.max_error_rate_ratio == 2.0
        assert config.prometheus_url == "http://localhost:9090"

    def test_to_dict(self) -> None:
        """Config should be serializable."""
        config = DeploymentConfig()
        d = config.model_dump()
        assert "canary_duration_minutes" in d
        assert "max_error_rate_ratio" in d
        assert "prometheus_url" in d

    def test_weight_constraints(self) -> None:
        """Weights should be constrained between 1 and 10."""
        config = DeploymentConfig(canary_weight=10, champion_weight=1)
        assert config.canary_weight == 10
        assert config.champion_weight == 1

    def test_error_rate_constraints(self) -> None:
        """Absolute max error rate should be between 0 and 1."""
        config = DeploymentConfig(absolute_max_error_rate=0.0)
        assert config.absolute_max_error_rate == 0.0
        config = DeploymentConfig(absolute_max_error_rate=1.0)
        assert config.absolute_max_error_rate == 1.0
