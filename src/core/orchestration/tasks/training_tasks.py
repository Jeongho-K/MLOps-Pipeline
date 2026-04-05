"""Prefect tasks for training operations."""

from __future__ import annotations

import logging

from prefect import task
from prefect.artifacts import create_markdown_artifact

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
    mlflow_tracking_uri: str = "http://localhost:5000",
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
    from src.plugins.cv.configs.train_config import TrainConfig
    from src.plugins.cv.trainer import train

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
        num_workers=0,  # Avoid subprocess forking issues inside Prefect task execution
    )

    metrics = train(config)
    logger.info("Training complete: %s", metrics)

    # Create Prefect artifact for training results
    metric_rows = ""
    for key, value in metrics.items():
        metric_rows += f"| {key} | {value:.4f} |\n"

    markdown = f"""## Training Results
| Metric | Value |
|--------|-------|
{metric_rows}
**Model:** {model_name} | **Epochs:** {epochs} | **Batch Size:** {batch_size}
"""
    create_markdown_artifact(key="training-results", markdown=markdown)

    return metrics
