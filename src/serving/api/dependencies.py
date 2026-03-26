"""Model loading and management for the inference API."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import mlflow.pytorch
import torch

logger = logging.getLogger(__name__)


@dataclass
class ModelState:
    """Holds the currently loaded model and its metadata."""

    model: torch.nn.Module | None = None
    model_name: str = ""
    model_version: str = ""
    num_classes: int = 0
    device: torch.device = field(default_factory=lambda: torch.device("cpu"))
    image_size: int = 224

    @property
    def is_loaded(self) -> bool:
        """Check if a model is currently loaded."""
        return self.model is not None


def resolve_device(device_str: str) -> torch.device:
    """Resolve device string to torch.device for inference.

    Args:
        device_str: "auto", "cpu", "cuda", or "mps".

    Returns:
        Resolved torch.device.
    """
    if device_str == "auto":
        if torch.cuda.is_available():
            return torch.device("cuda")
        if torch.backends.mps.is_available():
            return torch.device("mps")
        return torch.device("cpu")

    return torch.device(device_str)


def load_model_from_registry(
    model_name: str,
    model_version: str,
    mlflow_tracking_uri: str,
    device: torch.device,
    image_size: int,
) -> ModelState:
    """Load a PyTorch model from MLflow Model Registry.

    Args:
        model_name: Registered model name in MLflow.
        model_version: Model version ("latest" or a specific version number).
        mlflow_tracking_uri: MLflow tracking server URI.
        device: Device to load the model onto.
        image_size: Expected input image size.

    Returns:
        ModelState with the loaded model and metadata.

    Raises:
        RuntimeError: If model loading fails.
    """
    mlflow.set_tracking_uri(mlflow_tracking_uri)

    model_uri = f"models:/{model_name}/{model_version}"
    logger.info("Loading model from %s on device %s", model_uri, device)

    try:
        model = mlflow.pytorch.load_model(model_uri)
    except Exception as exc:
        raise RuntimeError(
            f"Failed to load model '{model_uri}' from MLflow at {mlflow_tracking_uri}: {exc}"
        ) from exc

    model = model.to(device)
    model.eval()  # noqa: S307 - PyTorch eval mode, not builtin eval()

    # Detect num_classes from the final layer
    num_classes = _detect_num_classes(model)

    logger.info(
        "Model loaded: %s (version=%s, num_classes=%d, device=%s)",
        model_name, model_version, num_classes, device,
    )

    return ModelState(
        model=model,
        model_name=model_name,
        model_version=model_version,
        num_classes=num_classes,
        device=device,
        image_size=image_size,
    )


def _detect_num_classes(model: torch.nn.Module) -> int:
    """Detect the number of output classes from the model's final layer.

    Args:
        model: PyTorch model.

    Returns:
        Number of output classes, or 0 if detection fails.
    """
    # ResNet family
    if hasattr(model, "fc") and hasattr(model.fc, "out_features"):
        return model.fc.out_features

    # EfficientNet / MobileNet family
    if hasattr(model, "classifier"):
        classifier = model.classifier
        if isinstance(classifier, torch.nn.Sequential):
            for layer in reversed(list(classifier)):
                if hasattr(layer, "out_features"):
                    return layer.out_features

    logger.warning("Could not detect num_classes from model architecture")
    return 0
