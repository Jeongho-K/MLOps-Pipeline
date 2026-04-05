"""Classification training loop with MLflow integration."""

from __future__ import annotations

import logging
from contextlib import nullcontext
from pathlib import Path

import mlflow
import mlflow.pytorch
import torch
import torch.nn as nn
from mlflow import MlflowClient
from mlflow.models import infer_signature
from torch.utils.data import DataLoader
from torchvision.datasets import ImageFolder

from src.common.device import resolve_device
from src.plugins.cv.transforms import get_eval_transforms, get_train_transforms
from src.plugins.cv.configs.train_config import TrainConfig  # noqa: TCH001 - used at runtime
from src.plugins.cv.models.classifier import create_classifier

logger = logging.getLogger(__name__)


def train(config: TrainConfig) -> dict[str, float]:
    """Run a full training loop with MLflow tracking.

    Args:
        config: Training configuration.

    Returns:
        Dictionary with keys 'train_loss', 'train_accuracy' (final epoch),
        'val_loss', 'val_accuracy' (final epoch),
        and 'best_val_accuracy' (best across all epochs).

    Raises:
        FileNotFoundError: If train or val subdirectory does not exist.
        ValueError: If model_name is unsupported.
        RuntimeError: If MLflow connection fails or device is unavailable.
    """
    device = resolve_device(config.device)
    logger.info("Using device: %s", device)
    pin_memory = device.type == "cuda"

    # Data loaders
    train_dir = Path(config.data_dir) / "train"
    val_dir = Path(config.data_dir) / "val"

    if not train_dir.exists():
        raise FileNotFoundError(f"Training data not found: {train_dir}")
    if not val_dir.exists():
        raise FileNotFoundError(f"Validation data not found: {val_dir}")

    train_dataset = ImageFolder(str(train_dir), transform=get_train_transforms(config.image_size))
    val_dataset = ImageFolder(str(val_dir), transform=get_eval_transforms(config.image_size))

    if len(train_dataset) == 0:
        raise RuntimeError(f"Training dataset is empty: {train_dir}")
    if len(val_dataset) == 0:
        raise RuntimeError(f"Validation dataset is empty: {val_dir}")

    train_loader = DataLoader(
        train_dataset,
        batch_size=config.batch_size,
        shuffle=True,
        num_workers=config.num_workers,
        pin_memory=pin_memory,
    )
    val_loader = DataLoader(
        val_dataset,
        batch_size=config.batch_size,
        shuffle=False,
        num_workers=config.num_workers,
        pin_memory=pin_memory,
    )

    logger.info("Train: %d images, Val: %d images", len(train_dataset), len(val_dataset))

    # Model
    model = create_classifier(config.model_name, config.num_classes, config.pretrained)
    model = model.to(device)

    criterion = nn.CrossEntropyLoss()
    optimizer = torch.optim.AdamW(
        model.parameters(),
        lr=config.learning_rate,
        weight_decay=config.weight_decay,
    )

    # MLflow tracking
    mlflow.set_tracking_uri(config.mlflow_tracking_uri)
    mlflow.set_experiment(config.experiment_name)

    # Enable autolog for automatic parameter/metric capture (models logged manually)
    mlflow.pytorch.autolog(log_models=False, log_every_n_epoch=None)
    mlflow.enable_system_metrics_logging()

    with mlflow.start_run() as run:
        # Log parameters
        mlflow.log_params(
            {
                "model_name": config.model_name,
                "num_classes": config.num_classes,
                "pretrained": config.pretrained,
                "epochs": config.epochs,
                "batch_size": config.batch_size,
                "learning_rate": config.learning_rate,
                "weight_decay": config.weight_decay,
                "image_size": config.image_size,
                "device": str(device),
                "train_samples": len(train_dataset),
                "val_samples": len(val_dataset),
            }
        )

        best_val_acc = 0.0
        best_state_dict: dict[str, torch.Tensor] | None = None
        train_loss = 0.0
        train_acc = 0.0
        val_loss = 0.0
        val_acc = 0.0

        for epoch in range(config.epochs):
            # Training phase
            train_loss, train_acc = _run_epoch(
                model,
                train_loader,
                criterion,
                optimizer,
                device,
                training=True,
            )

            # Validation phase
            val_loss, val_acc = _run_epoch(
                model,
                val_loader,
                criterion,
                None,
                device,
                training=False,
            )

            # Log metrics
            mlflow.log_metrics(
                {
                    "train_loss": train_loss,
                    "train_accuracy": train_acc,
                    "val_loss": val_loss,
                    "val_accuracy": val_acc,
                },
                step=epoch,
            )

            logger.info(
                "Epoch %d/%d — train_loss=%.4f train_acc=%.4f val_loss=%.4f val_acc=%.4f",
                epoch + 1,
                config.epochs,
                train_loss,
                train_acc,
                val_loss,
                val_acc,
            )

            # Track best model
            if val_acc > best_val_acc:
                best_val_acc = val_acc
                best_state_dict = {k: v.cpu().clone() for k, v in model.state_dict().items()}

        # Restore best model weights
        if best_state_dict is not None:
            model.load_state_dict(best_state_dict)

        # Log final metrics
        mlflow.log_metric("best_val_accuracy", best_val_acc)

        # Log model to MLflow (in evaluation mode) with signature and input example
        model.eval()
        try:
            sample_input = torch.randn(1, 3, config.image_size, config.image_size)
            with torch.no_grad():
                sample_output = model(sample_input.to(device))
            signature = infer_signature(
                sample_input.numpy(),
                sample_output.cpu().numpy(),
            )

            model_info = mlflow.pytorch.log_model(
                model,
                name="model",
                signature=signature,
                input_example=sample_input.numpy(),
                registered_model_name=config.registered_model_name,
            )
        except Exception:
            logger.exception(
                "Failed to log model to MLflow. Training metrics are still recorded in run %s.",
                run.info.run_id,
            )
            model_info = None

        # Set model alias if model was registered (separate try block)
        try:
            if config.registered_model_name and model_info and model_info.registered_model_version:
                client = MlflowClient()
                client.set_registered_model_alias(
                    name=config.registered_model_name,
                    alias="challenger",
                    version=model_info.registered_model_version,
                )
                logger.info(
                    "Set alias 'challenger' on %s version %s",
                    config.registered_model_name,
                    model_info.registered_model_version,
                )
        except Exception:
            logger.exception(
                "Failed to set model alias for %s. Model is logged but alias was not set.",
                config.registered_model_name,
            )

        logger.info("Run %s complete. Best val accuracy: %.4f", run.info.run_id, best_val_acc)

    return {
        "train_loss": train_loss,
        "train_accuracy": train_acc,
        "val_loss": val_loss,
        "val_accuracy": val_acc,
        "best_val_accuracy": best_val_acc,
    }


def _run_epoch(
    model: nn.Module,
    loader: DataLoader,
    criterion: nn.Module,
    optimizer: torch.optim.Optimizer | None,
    device: torch.device,
    training: bool,
) -> tuple[float, float]:
    """Run one training or evaluation epoch.

    Args:
        model: PyTorch model.
        loader: DataLoader for the split.
        criterion: Loss function.
        optimizer: Optimizer (None for evaluation).
        device: Device to use.
        training: Whether to run in training mode.

    Returns:
        Tuple of (average loss, accuracy).

    Raises:
        RuntimeError: If no samples were processed (empty dataset).
    """
    if training:
        model.train()
    else:
        model.eval()

    total_loss = 0.0
    correct = 0
    total = 0

    ctx = nullcontext() if training else torch.no_grad()
    with ctx:
        for inputs, targets in loader:
            inputs, targets = inputs.to(device), targets.to(device)

            outputs = model(inputs)
            loss = criterion(outputs, targets)

            if training and optimizer is not None:
                optimizer.zero_grad()
                loss.backward()
                optimizer.step()

            total_loss += loss.item() * inputs.size(0)
            _, predicted = outputs.max(1)
            correct += predicted.eq(targets).sum().item()
            total += targets.size(0)

    if total == 0:
        raise RuntimeError(
            "No samples were processed during the epoch. Check that the dataset directory contains valid images."
        )

    avg_loss = total_loss / total
    accuracy = correct / total

    return avg_loss, accuracy
