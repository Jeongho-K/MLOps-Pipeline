"""Unit tests for serving configuration."""

from src.core.serving.api.config import ServingConfig


class TestServingConfig:
    """Tests for ServingConfig defaults and overrides."""

    def test_default_values(self) -> None:
        """Default config should have expected values."""
        config = ServingConfig()
        assert config.model_name == "cv-classifier"
        assert config.model_version == "@champion"
        assert config.mlflow_tracking_uri == "http://mlflow:5000"
        assert config.image_size == 224
        assert config.device == "auto"
        assert config.host == "0.0.0.0"
        assert config.port == 8000
        assert config.class_names is None

    def test_override_values(self) -> None:
        """Config should accept overrides."""
        config = ServingConfig(
            model_name="resnet50-prod",
            model_version="3",
            device="cpu",
            port=9090,
        )
        assert config.model_name == "resnet50-prod"
        assert config.model_version == "3"
        assert config.device == "cpu"
        assert config.port == 9090

    def test_class_names_parsing(self) -> None:
        """Class names should be parsed from comma-separated string."""
        config = ServingConfig(class_names="cat,dog,bird")
        names = config.get_class_names_list()
        assert names == ["cat", "dog", "bird"]

    def test_class_names_none(self) -> None:
        """None class names should return None."""
        config = ServingConfig(class_names=None)
        assert config.get_class_names_list() is None

    def test_class_names_with_spaces(self) -> None:
        """Class names with spaces should be trimmed."""
        config = ServingConfig(class_names=" cat , dog , bird ")
        names = config.get_class_names_list()
        assert names == ["cat", "dog", "bird"]

    def test_to_dict(self) -> None:
        """Config should be serializable."""
        config = ServingConfig()
        d = config.model_dump()
        assert "model_name" in d
        assert "mlflow_tracking_uri" in d
        assert "image_size" in d
