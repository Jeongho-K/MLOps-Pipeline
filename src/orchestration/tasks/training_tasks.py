"""Prefect tasks for training operations."""

from __future__ import annotations

import logging

from prefect import task

logger = logging.getLogger(__name__)


@task(name="train-model", retries=0, timeout_seconds=7200)
def train_model(
    data_dir: str,
    model_name: str = "resnet18",
    num_classes: int = 10,
    epochs: int = 10,
    batch_size: int = 32,
    learning_rate: float = 1e-3,
    experiment_name: str = "default-classification",
    mlflow_tracking_uri: str = "http://mlflow:5000",
    registered_model_name: str | None = None,
) -> dict[str, float]:
    """Run model training with MLflow tracking.

    Args:
        data_dir: Path to dataset directory.
        model_name: Model architecture name.
        num_classes: Number of output classes.
        epochs: Number of training epochs.
        batch_size: Batch size.
        learning_rate: Initial learning rate.
        experiment_name: MLflow experiment name.
        mlflow_tracking_uri: MLflow server URI.
        registered_model_name: Optional model registry name.

    Returns:
        Dictionary of training metrics.
    """
    from src.training.configs.train_config import TrainConfig
    from src.training.trainers.classification_trainer import train

    config = TrainConfig(
        data_dir=data_dir,
        model_name=model_name,
        num_classes=num_classes,
        epochs=epochs,
        batch_size=batch_size,
        learning_rate=learning_rate,
        experiment_name=experiment_name,
        mlflow_tracking_uri=mlflow_tracking_uri,
        registered_model_name=registered_model_name,
        num_workers=0,  # Prefect workers handle parallelism
    )

    metrics = train(config)
    logger.info("Training complete: %s", metrics)
    return metrics
