"""End-to-end training pipeline flow.

Orchestrates: data preparation → image validation → model training → (optional) label validation.
Designed to be run as a Prefect deployment with scheduling.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from prefect import flow

from src.core.orchestration.tasks.data_tasks import prepare_dataset, validate_images
from src.core.orchestration.tasks.training_tasks import train_model

if TYPE_CHECKING:
    from prefect import Flow
    from prefect.client.schemas.objects import FlowRun
    from prefect.states import State

logger = logging.getLogger(__name__)


def on_pipeline_failure(flow: Flow, flow_run: FlowRun, state: State) -> None:
    """Log pipeline failure details for alerting."""
    logger.error(
        "Pipeline '%s' (run=%s) failed: %s",
        flow.name,
        flow_run.name,
        state.message,
    )


def on_pipeline_completion(flow: Flow, flow_run: FlowRun, state: State) -> None:
    """Log pipeline completion for tracking."""
    logger.info(
        "Pipeline '%s' (run=%s) completed successfully.",
        flow.name,
        flow_run.name,
    )


@flow(
    name="training-pipeline",
    log_prints=True,
    retries=0,
    description="End-to-end CV model training: data prep → validation → training",
    on_failure=[on_pipeline_failure],
    on_completion=[on_pipeline_completion],
)
def training_pipeline(
    data_dir: str = "data/raw/cifar10-demo",
    model_name: str = "resnet18",
    num_classes: int = 10,
    epochs: int = 10,
    batch_size: int = 32,
    learning_rate: float = 1e-3,
    experiment_name: str = "default-classification",
    mlflow_tracking_uri: str = "http://localhost:5000",
    registered_model_name: str | None = None,
    min_health_score: float = 0.5,
    run_label_validation: bool = False,
) -> dict[str, float]:
    """Run the full training pipeline.

    Steps:
        1. Prepare dataset (verify existence and structure)
        2. Validate image quality (CleanVision)
        3. Train model (PyTorch + MLflow tracking)
        4. (Optional) Validate labels (CleanLab, post-hoc)

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
        run_label_validation: Whether to run CleanLab label validation after training.

    Returns:
        Dictionary of training metrics.

    Raises:
        RuntimeError: If data health score is below min_health_score.
    """
    # Step 1: Prepare dataset
    dataset_path = prepare_dataset(data_dir)

    # Step 2: Validate images
    validation_metrics = validate_images(str(dataset_path))
    if "health_score" not in validation_metrics:
        raise RuntimeError(
            f"Validation output missing 'health_score' key. Got keys: {list(validation_metrics.keys())}."
        )
    health_score = validation_metrics["health_score"]

    if health_score < min_health_score:
        raise RuntimeError(
            f"Data health score ({health_score:.2f}) is below minimum ({min_health_score:.2f}). "
            "Fix data quality issues before training."
        )

    logger.info("Data validation passed (health_score=%.2f)", health_score)

    # Step 3: Train model
    metrics = train_model(
        data_dir=str(dataset_path),
        model_name=model_name,
        num_classes=num_classes,
        epochs=epochs,
        batch_size=batch_size,
        learning_rate=learning_rate,
        experiment_name=experiment_name,
        mlflow_tracking_uri=mlflow_tracking_uri,
        registered_model_name=registered_model_name,
    )

    # Step 4: Optional label validation (post-hoc using trained model)
    if run_label_validation:
        try:
            _run_post_hoc_label_validation(
                data_dir=str(dataset_path),
                num_classes=num_classes,
                mlflow_tracking_uri=mlflow_tracking_uri,
                registered_model_name=registered_model_name,
            )
        except Exception:
            logger.warning(
                "Label validation failed, but training completed successfully.",
                exc_info=True,
            )

    logger.info("Pipeline complete: %s", metrics)
    return metrics


def _run_post_hoc_label_validation(
    data_dir: str,
    num_classes: int,
    mlflow_tracking_uri: str,
    registered_model_name: str | None,
) -> None:
    """Run label validation using the most recently trained model.

    Args:
        data_dir: Path to dataset directory.
        num_classes: Number of output classes.
        mlflow_tracking_uri: MLflow tracking server URI.
        registered_model_name: Model name in MLflow registry.
    """
    from src.core.orchestration.tasks.data_tasks import validate_labels_task

    if not registered_model_name:
        logger.warning("Label validation skipped: no registered_model_name provided.")
        return

    model_uri = f"models:/{registered_model_name}@challenger"

    from src.common.device import resolve_device

    device = str(resolve_device("auto"))
    label_metrics = validate_labels_task(
        model_uri=model_uri,
        data_dir=data_dir,
        device=device,
        num_classes=num_classes,
        mlflow_tracking_uri=mlflow_tracking_uri,
    )
    logger.info("Label validation results: %s", label_metrics)
