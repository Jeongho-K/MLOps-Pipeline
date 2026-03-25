"""End-to-end training pipeline flow.

Orchestrates: data preparation → image validation → model training.
Designed to be run as a Prefect deployment with scheduling.
"""

from __future__ import annotations

import logging

from prefect import flow

from src.orchestration.tasks.data_tasks import prepare_dataset, validate_images
from src.orchestration.tasks.training_tasks import train_model

logger = logging.getLogger(__name__)


@flow(
    name="training-pipeline",
    log_prints=True,
    retries=0,
    description="End-to-end CV model training: data prep → validation → training",
)
def training_pipeline(
    data_dir: str = "data/raw/cifar10-demo",
    model_name: str = "resnet18",
    num_classes: int = 10,
    epochs: int = 10,
    batch_size: int = 32,
    learning_rate: float = 1e-3,
    experiment_name: str = "default-classification",
    mlflow_tracking_uri: str = "http://mlflow:5000",
    registered_model_name: str | None = None,
    min_health_score: float = 0.5,
) -> dict[str, float]:
    """Run the full training pipeline.

    Steps:
        1. Prepare dataset (verify existence and structure)
        2. Validate image quality (CleanVision)
        3. Train model (PyTorch + MLflow tracking)

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
        min_health_score: Minimum data health score to proceed with training.

    Returns:
        Dictionary of training metrics.

    Raises:
        RuntimeError: If data health score is below min_health_score.
    """
    # Step 1: Prepare dataset
    dataset_path = prepare_dataset(data_dir)

    # Step 2: Validate images
    validation_metrics = validate_images(dataset_path)
    health_score = validation_metrics.get("health_score", 0.0)

    if health_score < min_health_score:
        raise RuntimeError(
            f"Data health score ({health_score:.2f}) is below minimum ({min_health_score:.2f}). "
            "Fix data quality issues before training."
        )

    logger.info("Data validation passed (health_score=%.2f)", health_score)

    # Step 3: Train model
    metrics = train_model(
        data_dir=data_dir,
        model_name=model_name,
        num_classes=num_classes,
        epochs=epochs,
        batch_size=batch_size,
        learning_rate=learning_rate,
        experiment_name=experiment_name,
        mlflow_tracking_uri=mlflow_tracking_uri,
        registered_model_name=registered_model_name,
    )

    logger.info("Pipeline complete: %s", metrics)
    return metrics
