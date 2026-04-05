"""Unit tests for training configuration."""

from src.plugins.cv.configs.train_config import TrainConfig


class TestTrainConfig:
    """Tests for TrainConfig defaults and overrides."""

    def test_default_values(self) -> None:
        """Default config should have expected values."""
        config = TrainConfig()
        assert config.model_name == "resnet18"
        assert config.num_classes == 10
        assert config.epochs == 10
        assert config.batch_size == 32
        assert config.learning_rate == 1e-3
        assert config.device == "auto"

    def test_override_values(self) -> None:
        """Config should accept overrides."""
        config = TrainConfig(
            model_name="resnet50",
            num_classes=100,
            epochs=50,
            batch_size=64,
        )
        assert config.model_name == "resnet50"
        assert config.num_classes == 100
        assert config.epochs == 50
        assert config.batch_size == 64

    def test_to_dict(self) -> None:
        """Config should be serializable."""
        config = TrainConfig()
        d = config.model_dump()
        assert "model_name" in d
        assert "learning_rate" in d
        assert "mlflow_tracking_uri" in d
