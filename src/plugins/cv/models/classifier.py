"""Image classification models using torchvision pretrained architectures."""

from __future__ import annotations

import logging

import torch.nn as nn
from torchvision import models

logger = logging.getLogger(__name__)

SUPPORTED_MODELS = {
    "resnet18": models.resnet18,
    "resnet34": models.resnet34,
    "resnet50": models.resnet50,
    "efficientnet_b0": models.efficientnet_b0,
    "efficientnet_b1": models.efficientnet_b1,
    "mobilenet_v3_small": models.mobilenet_v3_small,
    "mobilenet_v3_large": models.mobilenet_v3_large,
}


def create_classifier(
    model_name: str,
    num_classes: int,
    pretrained: bool = True,
) -> nn.Module:
    """Create a classification model with a custom head.

    Args:
        model_name: Architecture name. See SUPPORTED_MODELS.
        num_classes: Number of output classes.
        pretrained: Whether to use pretrained ImageNet weights.

    Returns:
        PyTorch model with the final layer replaced.

    Raises:
        ValueError: If model_name is not supported.
    """
    if model_name not in SUPPORTED_MODELS:
        raise ValueError(f"Unknown model '{model_name}'. Supported: {sorted(SUPPORTED_MODELS)}")
    if num_classes < 1:
        raise ValueError(f"num_classes must be >= 1, got {num_classes}")

    weights = "DEFAULT" if pretrained else None
    model = SUPPORTED_MODELS[model_name](weights=weights)

    # Replace the final classification head
    if model_name.startswith("resnet"):
        in_features = model.fc.in_features
        model.fc = nn.Linear(in_features, num_classes)
    elif model_name.startswith("efficientnet"):
        in_features = model.classifier[1].in_features
        model.classifier[1] = nn.Linear(in_features, num_classes)
    elif model_name.startswith("mobilenet"):
        in_features = model.classifier[3].in_features
        model.classifier[3] = nn.Linear(in_features, num_classes)
    else:
        raise NotImplementedError(
            f"Head replacement not implemented for '{model_name}'. Add the appropriate logic in create_classifier()."
        )

    logger.info(
        "Created %s (pretrained=%s, num_classes=%d)",
        model_name,
        pretrained,
        num_classes,
    )

    return model
