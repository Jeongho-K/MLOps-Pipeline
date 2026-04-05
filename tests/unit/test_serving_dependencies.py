"""Unit tests for model loading dependencies."""

from unittest.mock import MagicMock, patch

import torch

from src.common.device import resolve_device
from src.core.serving.api.dependencies import ModelState, _detect_num_classes


class TestModelState:
    """Tests for ModelState dataclass."""

    def test_not_loaded_by_default(self) -> None:
        """Default ModelState should report not loaded."""
        state = ModelState()
        assert state.is_loaded is False

    def test_loaded_with_model(self) -> None:
        """ModelState with a model should report loaded."""
        mock_model = MagicMock()
        state = ModelState(model=mock_model, model_name="test", num_classes=10)
        assert state.is_loaded is True


class TestResolveDevice:
    """Tests for resolve_device function."""

    def test_cpu(self) -> None:
        """Should return CPU device."""
        device = resolve_device("cpu")
        assert device == torch.device("cpu")

    @patch("src.common.device.torch.cuda.is_available", return_value=True)
    def test_auto_with_cuda(self, _mock_cuda) -> None:
        """Auto should prefer CUDA when available."""
        device = resolve_device("auto")
        assert device == torch.device("cuda")

    @patch("src.common.device.torch.cuda.is_available", return_value=False)
    @patch("src.common.device.torch.backends.mps.is_available", return_value=False)
    def test_auto_fallback_cpu(self, _mock_mps, _mock_cuda) -> None:
        """Auto should fall back to CPU when no GPU available."""
        device = resolve_device("auto")
        assert device == torch.device("cpu")


class TestDetectNumClasses:
    """Tests for _detect_num_classes function."""

    def test_resnet_detection(self) -> None:
        """Should detect num_classes from ResNet fc layer."""
        model = MagicMock()
        model.fc = torch.nn.Linear(512, 10)
        del model.classifier  # Ensure classifier doesn't exist
        assert _detect_num_classes(model) == 10

    def test_efficientnet_detection(self) -> None:
        """Should detect num_classes from EfficientNet classifier."""
        model = MagicMock()
        del model.fc
        model.classifier = torch.nn.Sequential(
            torch.nn.Dropout(0.2),
            torch.nn.Linear(1280, 5),
        )
        assert _detect_num_classes(model) == 5

    def test_unknown_architecture(self) -> None:
        """Should return 0 for unknown architectures."""
        model = MagicMock()
        del model.fc
        del model.classifier
        assert _detect_num_classes(model) == 0


class TestLoadModelFromRegistry:
    """Tests for load_model_from_registry function."""

    def test_alias_uri_format(self) -> None:
        """Version starting with @ constructs models:/{name}@{alias} URI."""
        from src.core.serving.api.dependencies import load_model_from_registry

        mock_model = MagicMock()
        mock_model.fc = torch.nn.Linear(512, 10)
        del mock_model.classifier

        mock_mv = MagicMock()
        mock_mv.run_id = "run-123"

        with (
            patch("src.core.serving.api.dependencies.mlflow.set_tracking_uri"),
            patch(
                "src.core.serving.api.dependencies.mlflow.pytorch.load_model",
                return_value=mock_model,
            ) as mock_load,
            patch("src.core.serving.api.dependencies.MlflowClient") as mock_client_cls,
        ):
            mock_client_cls.return_value.get_model_version_by_alias.return_value = mock_mv

            result = load_model_from_registry(
                model_name="my-model",
                model_version="@champion",
                mlflow_tracking_uri="http://mlflow:5000",
                device=torch.device("cpu"),
                image_size=224,
            )

        mock_load.assert_called_once_with("models:/my-model@champion", map_location="cpu")
        assert result.mlflow_run_id == "run-123"

    def test_numeric_version_uri_format(self) -> None:
        """Numeric version constructs models:/{name}/{version} URI."""
        from src.core.serving.api.dependencies import load_model_from_registry

        mock_model = MagicMock()
        mock_model.fc = torch.nn.Linear(512, 5)
        del mock_model.classifier

        mock_mv = MagicMock()
        mock_mv.run_id = "run-456"

        with (
            patch("src.core.serving.api.dependencies.mlflow.set_tracking_uri"),
            patch(
                "src.core.serving.api.dependencies.mlflow.pytorch.load_model",
                return_value=mock_model,
            ) as mock_load,
            patch("src.core.serving.api.dependencies.MlflowClient") as mock_client_cls,
        ):
            mock_client_cls.return_value.get_model_version.return_value = mock_mv

            result = load_model_from_registry(
                model_name="my-model",
                model_version="3",
                mlflow_tracking_uri="http://mlflow:5000",
                device=torch.device("cpu"),
                image_size=224,
            )

        mock_load.assert_called_once_with("models:/my-model/3", map_location="cpu")
        assert result.mlflow_run_id == "run-456"

    def test_source_run_id_graceful_degradation(self) -> None:
        """When MlflowClient raises, run_id defaults to empty string."""
        from src.core.serving.api.dependencies import load_model_from_registry

        mock_model = MagicMock()
        mock_model.fc = torch.nn.Linear(512, 10)
        del mock_model.classifier

        with (
            patch("src.core.serving.api.dependencies.mlflow.set_tracking_uri"),
            patch(
                "src.core.serving.api.dependencies.mlflow.pytorch.load_model",
                return_value=mock_model,
            ),
            patch("src.core.serving.api.dependencies.MlflowClient") as mock_client_cls,
        ):
            mock_client_cls.return_value.get_model_version_by_alias.side_effect = Exception("connection error")

            result = load_model_from_registry(
                model_name="my-model",
                model_version="@champion",
                mlflow_tracking_uri="http://mlflow:5000",
                device=torch.device("cpu"),
                image_size=224,
            )

        assert result.mlflow_run_id == ""
        assert result.is_loaded is True
