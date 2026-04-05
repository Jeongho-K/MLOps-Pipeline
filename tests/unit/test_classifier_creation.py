"""Unit tests for model creation."""

import pytest
import torch
import torch.nn as nn

from src.plugins.cv.models.classifier import SUPPORTED_MODELS, create_classifier


class TestCreateClassifier:
    """Tests for create_classifier function."""

    def test_resnet18_default(self) -> None:
        """ResNet18 should be created with correct output size."""
        model = create_classifier("resnet18", num_classes=10, pretrained=False)
        assert isinstance(model, nn.Module)
        assert model.fc.out_features == 10

    def test_efficientnet_b0(self) -> None:
        """EfficientNet-B0 should have modified classifier."""
        model = create_classifier("efficientnet_b0", num_classes=5, pretrained=False)
        assert isinstance(model, nn.Module)
        assert model.classifier[1].out_features == 5

    def test_mobilenet_v3_small(self) -> None:
        """MobileNetV3-Small should have modified classifier."""
        model = create_classifier("mobilenet_v3_small", num_classes=3, pretrained=False)
        assert isinstance(model, nn.Module)
        assert model.classifier[3].out_features == 3

    def test_unsupported_model_raises(self) -> None:
        """Unknown model name should raise ValueError."""
        with pytest.raises(ValueError, match="Unknown model"):
            create_classifier("nonexistent_model", num_classes=10)

    def test_all_supported_models(self) -> None:
        """All supported models should be creatable with correct output size."""
        for name in SUPPORTED_MODELS:
            model = create_classifier(name, num_classes=2, pretrained=False)
            assert isinstance(model, nn.Module)
            # Verify output shape with a dummy forward pass
            dummy = torch.randn(1, 3, 224, 224)
            output = model(dummy)
            assert output.shape == (1, 2), f"{name}: expected (1,2), got {output.shape}"

    def test_num_classes_zero_raises(self) -> None:
        """Zero num_classes should raise ValueError."""
        with pytest.raises(ValueError, match="num_classes must be >= 1"):
            create_classifier("resnet18", num_classes=0)
