"""Continuous Training pipeline flow (Phase B).

Master orchestration flow that closes the Data Flywheel loop:
event trigger → data integration → G1 → DVC version → train → G2 → G3 → champion promotion.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from prefect import flow
from prefect.artifacts import create_markdown_artifact

from src.orchestration.tasks.continuous_training_tasks import (
    check_champion_gate,
    check_training_quality,
    integrate_training_data,
    promote_to_champion,
    resolve_round_number,
)
from src.orchestration.tasks.data_tasks import validate_images

if TYPE_CHECKING:
    from prefect import Flow
    from prefect.client.schemas.objects import FlowRun
    from prefect.states import State

logger = logging.getLogger(__name__)


def on_ct_failure(flow: Flow, flow_run: FlowRun, state: State) -> None:
    """Log continuous training pipeline failure for alerting."""
    logger.error(
        "Continuous training '%s' (run=%s) failed: %s",
        flow.name,
        flow_run.name,
        state.message,
    )


def on_ct_completion(flow: Flow, flow_run: FlowRun, state: State) -> None:
    """Log continuous training pipeline completion."""
    logger.info(
        "Continuous training '%s' (run=%s) completed successfully.",
        flow.name,
        flow_run.name,
    )


@flow(
    name="continuous-training",
    log_prints=True,
    retries=0,
    description=(
        "Phase B continuous training loop: "
        "data integration → G1 → train → G2 → G3 → champion promotion"
    ),
    on_failure=[on_ct_failure],
    on_completion=[on_ct_completion],
)
def continuous_training_flow(
    trigger_source: str = "manual",
    round_num: int | None = None,
    # S3 connection
    s3_endpoint: str = "http://minio:9000",
    s3_access_key: str = "",
    s3_secret_key: str = "",
    # Data integration
    accumulation_bucket: str = "active-learning",
    accumulation_prefix: str = "accumulated/",
    merged_data_dir: str = "data/merged",
    train_val_split: float = 0.8,
    # Label Studio
    label_studio_url: str = "http://label-studio:8080",
    label_studio_api_key: str = "",
    label_studio_project_id: int = 1,
    # Training params (passthrough to training_pipeline)
    model_name: str = "resnet18",
    num_classes: int = 10,
    epochs: int = 10,
    batch_size: int = 32,
    learning_rate: float = 1e-3,
    experiment_name: str = "continuous-training",
    mlflow_tracking_uri: str = "http://localhost:5000",
    registered_model_name: str = "cv-classifier",
    # G1: Data quality gate
    min_health_score: float = 0.5,
    # G2: Training quality gate
    min_val_accuracy: float = 0.7,
    max_overfit_gap: float = 0.15,
    # G3: Champion gate
    champion_metric: str = "best_val_accuracy",
    champion_margin: float = 0.0,
    # Round tracking
    round_state_bucket: str = "active-learning",
    round_state_key: str = "rounds/round_state.json",
) -> dict:
    """Run the continuous training loop.

    This is the master flow for Phase B. It orchestrates the full cycle:
    event trigger → data integration → quality validation → training →
    quality gates → champion promotion.

    Args:
        trigger_source: What triggered this flow (labeling_complete, drift_detected,
            data_accumulated, manual).
        round_num: Explicit round number. If None, auto-increments.
        s3_endpoint: S3-compatible endpoint URL.
        s3_access_key: AWS/MinIO access key ID.
        s3_secret_key: AWS/MinIO secret access key.
        accumulation_bucket: S3 bucket for accumulated pseudo-labels.
        accumulation_prefix: S3 key prefix for accumulated data.
        merged_data_dir: Output directory for merged training data.
        train_val_split: Fraction of data for training.
        label_studio_url: Label Studio API base URL.
        label_studio_api_key: Label Studio API token.
        label_studio_project_id: Label Studio project ID.
        model_name: Model architecture name.
        num_classes: Number of output classes.
        epochs: Number of training epochs.
        batch_size: Batch size.
        learning_rate: Initial learning rate.
        experiment_name: MLflow experiment name.
        mlflow_tracking_uri: MLflow server URI.
        registered_model_name: MLflow registered model name.
        min_health_score: Minimum data health score for G1 gate.
        min_val_accuracy: Minimum validation accuracy for G2 gate.
        max_overfit_gap: Maximum overfitting gap for G2 gate.
        champion_metric: Metric to compare for G3 gate.
        champion_margin: Required improvement margin for G3 gate.
        round_state_bucket: S3 bucket for round state.
        round_state_key: S3 key for round state JSON.

    Returns:
        Dictionary summarizing the pipeline run including gate results.

    Raises:
        RuntimeError: If any quality gate fails.
    """
    logger.info("Continuous training triggered by: %s", trigger_source)

    # Step 1: Resolve round number
    current_round = resolve_round_number(
        s3_endpoint=s3_endpoint,
        s3_access_key=s3_access_key,
        s3_secret_key=s3_secret_key,
        bucket=round_state_bucket,
        state_key=round_state_key,
        explicit_round=round_num,
    )
    logger.info("AL round: %d", current_round)

    # Step 2: Integrate training data (merge pseudo-labels + human annotations)
    integration_result = integrate_training_data(
        label_studio_url=label_studio_url,
        label_studio_api_key=label_studio_api_key,
        label_studio_project_id=label_studio_project_id,
        s3_endpoint=s3_endpoint,
        s3_access_key=s3_access_key,
        s3_secret_key=s3_secret_key,
        accumulation_bucket=accumulation_bucket,
        accumulation_prefix=accumulation_prefix,
        output_dir=merged_data_dir,
        train_val_split=train_val_split,
    )

    total_samples = integration_result.get("total_samples", 0)
    if total_samples == 0:
        logger.warning("No data available for training. Pipeline ending early.")
        return {
            "status": "skipped",
            "reason": "No training data available",
            "trigger_source": trigger_source,
            "round": current_round,
        }

    # Step 3: G1 — Data quality gate (image validation)
    validation_metrics = validate_images(merged_data_dir)
    health_score = validation_metrics.get("health_score", 0.0)

    if health_score < min_health_score:
        raise RuntimeError(
            f"G1 Data Quality Gate failed: health_score ({health_score:.2f}) "
            f"< min ({min_health_score:.2f}). Round {current_round}."
        )
    logger.info("G1 Data Quality Gate passed (health_score=%.2f)", health_score)

    # Step 4: DVC versioning
    _version_data(
        merged_data_dir=merged_data_dir,
        round_num=current_round,
        mlflow_tracking_uri=mlflow_tracking_uri,
    )

    # Step 5: Training (call existing training_pipeline as subflow)
    from src.orchestration.flows.training_pipeline import training_pipeline

    training_metrics = training_pipeline(
        data_dir=merged_data_dir,
        model_name=model_name,
        num_classes=num_classes,
        epochs=epochs,
        batch_size=batch_size,
        learning_rate=learning_rate,
        experiment_name=experiment_name,
        mlflow_tracking_uri=mlflow_tracking_uri,
        registered_model_name=registered_model_name,
        min_health_score=0.0,  # Already validated in Step 3
    )

    # Step 6: G2 — Training quality gate
    g2_result = check_training_quality(
        metrics=training_metrics,
        min_val_accuracy=min_val_accuracy,
        max_overfit_gap=max_overfit_gap,
    )

    if not g2_result["passed"]:
        raise RuntimeError(
            f"G2 Training Quality Gate failed: {g2_result['reason']}. Round {current_round}."
        )
    logger.info("G2 Training Quality Gate passed")

    # Step 7: G3 — Champion gate
    g3_result = check_champion_gate(
        challenger_metrics=training_metrics,
        registered_model_name=registered_model_name,
        champion_metric=champion_metric,
        champion_margin=champion_margin,
        mlflow_tracking_uri=mlflow_tracking_uri,
    )

    if not g3_result["passed"]:
        raise RuntimeError(
            f"G3 Champion Gate failed: {g3_result['reason']}. Round {current_round}."
        )
    logger.info("G3 Champion Gate passed")

    # Step 8: Promote challenger to champion
    promotion_result = promote_to_champion(
        registered_model_name=registered_model_name,
        mlflow_tracking_uri=mlflow_tracking_uri,
    )

    # Step 9: Trigger canary deployment (Phase C)
    deployment_result = _trigger_canary_deployment(trigger_source)

    # Summary
    summary = {
        "status": "completed",
        "trigger_source": trigger_source,
        "round": current_round,
        "data_integration": integration_result,
        "health_score": health_score,
        "training_metrics": training_metrics,
        "g2_result": g2_result,
        "g3_result": g3_result,
        "promotion": promotion_result,
        "deployment": deployment_result,
    }

    _create_summary_artifact(summary)
    logger.info("Continuous training round %d complete: %s", current_round, summary)
    return summary


def _trigger_canary_deployment(trigger_source: str) -> dict:
    """Trigger the canary deployment flow as a subflow.

    Best-effort: logs warning if deployment fails but does not
    block the continuous training pipeline result.

    Args:
        trigger_source: What triggered the continuous training.

    Returns:
        Deployment result dict, or error info on failure.
    """
    try:
        from src.orchestration.flows.deployment_flow import deployment_flow

        result = deployment_flow(trigger_source=f"ct_{trigger_source}")
        logger.info("Canary deployment completed: %s", result.get("status"))
        return result
    except Exception:
        logger.warning(
            "Canary deployment failed. Champion was promoted but not deployed via canary.",
            exc_info=True,
        )
        return {"status": "failed", "reason": "deployment_flow exception"}


def _version_data(
    merged_data_dir: str,
    round_num: int,
    mlflow_tracking_uri: str,
) -> None:
    """Version merged training data with DVC.

    Best-effort: logs warning if DVC is not configured.

    Args:
        merged_data_dir: Path to the merged dataset.
        round_num: AL round number.
        mlflow_tracking_uri: MLflow tracking URI for cross-referencing.
    """
    try:
        from src.data.versioning.dvc_manager import DVCManager

        dvc = DVCManager()
        dvc.version_round(
            data_dir=merged_data_dir,
            round_num=round_num,
            mlflow_tracking_uri=mlflow_tracking_uri,
        )
        logger.info("DVC versioning complete for round %d", round_num)
    except Exception:
        logger.warning(
            "DVC versioning failed for round %d. Training will proceed without versioning.",
            round_num,
            exc_info=True,
        )


def _create_summary_artifact(summary: dict) -> None:
    """Create a Prefect markdown artifact summarizing the CT pipeline run.

    Args:
        summary: Pipeline summary dict.
    """
    integration = summary.get("data_integration", {})
    metrics = summary.get("training_metrics", {})
    g2 = summary.get("g2_result", {})
    g3 = summary.get("g3_result", {})
    promotion = summary.get("promotion", {})

    markdown = f"""## Continuous Training Pipeline — Round {summary.get("round", "?")}
**Trigger:** {summary.get("trigger_source", "unknown")} | **Status:** {summary.get("status", "unknown")}

### Data Integration
| Metric | Value |
|--------|-------|
| Human-labeled | {integration.get("human_labeled", 0)} |
| Pseudo-labeled | {integration.get("pseudo_labeled", 0)} |
| Total | {integration.get("total_samples", 0)} |
| Health Score (G1) | {summary.get("health_score", "N/A")} |

### Training Metrics
| Metric | Value |
|--------|-------|
| best_val_accuracy | {metrics.get("best_val_accuracy", "N/A")} |
| val_loss | {metrics.get("val_loss", "N/A")} |
| train_loss | {metrics.get("train_loss", "N/A")} |

### Quality Gates
| Gate | Result | Reason |
|------|--------|--------|
| G2 (Training Quality) | {"PASS" if g2.get("passed") else "FAIL"} | {g2.get("reason", "N/A")} |
| G3 (Champion Gate) | {"PASS" if g3.get("passed") else "FAIL"} | {g3.get("reason", "N/A")} |

### Champion Promotion
| Field | Value |
|-------|-------|
| Model | {promotion.get("registered_model_name", "N/A")} |
| Version | {promotion.get("version", "N/A")} |
"""
    create_markdown_artifact(key="continuous-training-summary", markdown=markdown)
