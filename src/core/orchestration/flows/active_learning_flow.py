"""Active Learning pipeline flow.

Orchestrates: fetch uncertain predictions -> select samples -> create Label Studio tasks.
Designed to be triggered by monitoring events (drift, low confidence) or scheduled.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from prefect import flow
from prefect.artifacts import create_markdown_artifact

from src.core.orchestration.tasks.active_learning_tasks import (
    create_labeling_tasks,
    fetch_uncertain_predictions,
    select_samples_for_labeling,
)

if TYPE_CHECKING:
    from prefect import Flow
    from prefect.client.schemas.objects import FlowRun
    from prefect.states import State

logger = logging.getLogger(__name__)


def on_flow_failure(flow: Flow, flow_run: FlowRun, state: State) -> None:
    """Log flow failure details for alerting."""
    logger.error(
        "Flow '%s' (run=%s) failed: %s",
        flow.name,
        flow_run.name,
        state.message,
    )


def on_flow_completion(flow: Flow, flow_run: FlowRun, state: State) -> None:
    """Log flow completion for tracking."""
    logger.info(
        "Flow '%s' (run=%s) completed successfully.",
        flow.name,
        flow_run.name,
    )


@flow(
    name="active-learning-pipeline",
    log_prints=True,
    retries=0,
    description="Collect uncertain samples and send to Label Studio for human review",
    on_failure=[on_flow_failure],
    on_completion=[on_flow_completion],
)
def active_learning_flow(
    s3_endpoint: str = "http://minio:9000",
    s3_access_key: str = "",
    s3_secret_key: str = "",
    prediction_logs_bucket: str = "prediction-logs",
    label_studio_url: str = "http://label-studio:8080",
    label_studio_api_key: str = "",
    label_studio_project_id: int = 1,
    max_samples: int = 100,
    lookback_days: int = 1,
) -> dict:
    """Active Learning pipeline: fetch uncertain predictions, select samples, create labeling tasks.

    Steps:
        1. Fetch prediction logs with routing_decision == "human_review"
        2. Select top-K most uncertain samples
        3. Create labeling tasks in Label Studio
        4. Return summary stats

    Args:
        s3_endpoint: S3-compatible endpoint URL.
        s3_access_key: AWS/MinIO access key ID.
        s3_secret_key: AWS/MinIO secret access key.
        prediction_logs_bucket: Bucket containing prediction logs.
        label_studio_url: Label Studio API base URL.
        label_studio_api_key: Label Studio API token.
        label_studio_project_id: Label Studio project ID.
        max_samples: Maximum number of samples to send for labeling.
        lookback_days: Number of past days to scan for uncertain predictions.

    Returns:
        Dictionary with pipeline summary including counts at each stage.
    """
    # Step 1: Fetch uncertain predictions
    predictions = fetch_uncertain_predictions(
        s3_endpoint=s3_endpoint,
        s3_access_key=s3_access_key,
        s3_secret_key=s3_secret_key,
        bucket=prediction_logs_bucket,
        lookback_days=lookback_days,
    )

    if not predictions:
        logger.info("No uncertain predictions found. Pipeline complete with no action.")
        summary = {
            "status": "completed",
            "total_uncertain": 0,
            "selected": 0,
            "tasks_created": 0,
        }
        _create_summary_artifact(summary)
        return summary

    # Step 2: Select top-K most uncertain samples
    selected = select_samples_for_labeling(
        predictions=predictions,
        max_samples=max_samples,
    )

    # Step 3: Create labeling tasks in Label Studio
    labeling_result = create_labeling_tasks(
        samples=selected,
        label_studio_url=label_studio_url,
        label_studio_api_key=label_studio_api_key,
        label_studio_project_id=label_studio_project_id,
    )

    summary = {
        "status": "completed",
        "total_uncertain": len(predictions),
        "selected": len(selected),
        "tasks_created": labeling_result.get("tasks_created", 0),
        "project_id": labeling_result.get("project_id", label_studio_project_id),
    }

    _create_summary_artifact(summary)
    logger.info("Active learning pipeline complete: %s", summary)
    return summary


def _create_summary_artifact(summary: dict) -> None:
    """Create a Prefect markdown artifact summarizing the AL pipeline run.

    Args:
        summary: Pipeline summary dict with counts.
    """
    markdown = f"""## Active Learning Pipeline Summary
| Metric | Value |
|--------|-------|
| Status | {summary.get("status", "unknown")} |
| Total Uncertain Predictions | {summary.get("total_uncertain", 0)} |
| Selected for Labeling | {summary.get("selected", 0)} |
| Tasks Created in Label Studio | {summary.get("tasks_created", 0)} |
| Label Studio Project ID | {summary.get("project_id", "N/A")} |
"""
    create_markdown_artifact(key="active-learning-summary", markdown=markdown)
