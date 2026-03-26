"""Unit tests for model loading dependencies."""

from unittest.mock import MagicMock, patch

import torch

from src.serving.api.dependencies import ModelState, _detect_num_classes, resolve_device


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

    @patch("src.serving.api.dependencies.torch.cuda.is_available", return_value=True)
    def test_auto_with_cuda(self, _mock_cuda) -> None:
        """Auto should prefer CUDA when available."""
        device = resolve_device("auto")
        assert device == torch.device("cuda")

    @patch("src.serving.api.dependencies.torch.cuda.is_available", return_value=False)
    @patch("src.serving.api.dependencies.torch.backends.mps.is_available", return_value=False)
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
