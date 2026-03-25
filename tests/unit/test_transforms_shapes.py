"""Unit tests for data preprocessing transforms."""

import torch
from PIL import Image

from src.data.preprocessing.transforms import get_eval_transforms, get_train_transforms


class TestTransforms:
    """Tests for image transform pipelines."""

    def test_train_transforms_output_shape(self) -> None:
        """Training transforms should produce correct tensor shape."""
        img = Image.new("RGB", (256, 256), color="red")
        transform = get_train_transforms(image_size=224)

        result = transform(img)

        assert isinstance(result, torch.Tensor)
        assert result.shape == (3, 224, 224)

    def test_eval_transforms_output_shape(self) -> None:
        """Eval transforms should produce correct tensor shape."""
        img = Image.new("RGB", (256, 256), color="blue")
        transform = get_eval_transforms(image_size=224)

        result = transform(img)

        assert isinstance(result, torch.Tensor)
        assert result.shape == (3, 224, 224)

    def test_custom_image_size(self) -> None:
        """Custom image sizes should be respected."""
        img = Image.new("RGB", (512, 512), color="green")

        for size in [128, 256, 384]:
            transform = get_eval_transforms(image_size=size)
            result = transform(img)
            assert result.shape == (3, size, size)

    def test_transforms_normalize_range(self) -> None:
        """Normalized outputs should not be in [0, 255] range."""
        img = Image.new("RGB", (256, 256), color=(128, 128, 128))
        transform = get_eval_transforms(image_size=224)

        result = transform(img)

        assert result.max() < 10.0
        assert result.min() > -10.0
