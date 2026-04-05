"""Standard image transforms for CV pipelines.

Provides reusable transform configurations for training, validation,
and inference. Uses torchvision.transforms.v2 API.
"""

from __future__ import annotations

import torch
from torchvision.transforms import v2


def get_train_transforms(image_size: int = 224) -> v2.Compose:
    """Get training transforms with augmentation.

    Args:
        image_size: Target image size (square).

    Returns:
        Composed transform pipeline.
    """
    return v2.Compose(
        [
            v2.RandomResizedCrop(image_size, scale=(0.8, 1.0)),
            v2.RandomHorizontalFlip(p=0.5),
            v2.ColorJitter(brightness=0.2, contrast=0.2, saturation=0.2),
            v2.ToImage(),
            v2.ToDtype(dtype=torch.float32, scale=True),
            v2.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
        ]
    )


def get_eval_transforms(image_size: int = 224) -> v2.Compose:
    """Get evaluation/inference transforms (no augmentation).

    Args:
        image_size: Target image size (square).

    Returns:
        Composed transform pipeline.
    """
    return v2.Compose(
        [
            v2.Resize(int(image_size * 1.14)),  # ~256px for 224 crop (standard ImageNet ratio)
            v2.CenterCrop(image_size),
            v2.ToImage(),
            v2.ToDtype(dtype=torch.float32, scale=True),
            v2.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
        ]
    )
