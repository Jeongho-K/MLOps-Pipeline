"""Data Accumulation pipeline flow.

Orchestrates: fetch pseudo-labels -> validate quality -> cleanup processed files.
Part of the Dual-Path Data Flywheel: high-confidence predictions are auto-accumulated
as pseudo-labels and periodically validated before merging into training data.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Coroutine

from prefect import flow
from prefect.artifacts import create_markdown_artifact

from src.core.orchestration.tasks.active_learning_tasks import (
    cleanup_accumulated,
    fetch_accumulated_samples,
    validate_accumulation_quality,
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
    name="data-accumulation-pipeline",
    log_prints=True,
    retries=0,
    description="Accumulate high-confidence pseudo-labels and validate quality",
    on_failure=[on_flow_failure],
    on_completion=[on_flow_completion],
)
def data_accumulation_flow(
    s3_endpoint: str = "http://minio:9000",
    s3_access_key: str = "",
    s3_secret_key: str = "",
    accumulation_bucket: str = "active-learning",
    accumulation_prefix: str = "accumulated/",
    existing_data_count: int = 0,
    max_pseudo_label_ratio: float = 0.3,
    min_samples: int = 50,
    trigger_retraining: bool = True,
) -> dict:
    """Data Accumulation pipeline: fetch pseudo-labels, validate, and report.

    Steps:
        1. Fetch accumulated pseudo-label samples from S3
        2. Validate quality (class distribution, ratio, min count)
        3. If valid, cleanup processed files
        4. Return summary stats

    When quality gate passes and ``trigger_retraining`` is True, triggers
    the continuous training deployment to merge accumulated data into
    training and retrain the model.

    Args:
        s3_endpoint: S3-compatible endpoint URL.
        s3_access_key: AWS/MinIO access key ID.
        s3_secret_key: AWS/MinIO secret access key.
        accumulation_bucket: S3 bucket for accumulated pseudo-labels.
        accumulation_prefix: S3 key prefix for accumulated data.
        existing_data_count: Number of existing training samples for ratio check.
        max_pseudo_label_ratio: Maximum pseudo-label ratio in total training data.
        min_samples: Minimum number of accumulated samples required.
        trigger_retraining: If True, trigger continuous training when quality gate passes.

    Returns:
        Dictionary with pipeline summary including quality gate results.
    """
    # Step 1: Fetch accumulated pseudo-label samples
    samples = fetch_accumulated_samples(
        s3_endpoint=s3_endpoint,
        s3_access_key=s3_access_key,
        s3_secret_key=s3_secret_key,
        bucket=accumulation_bucket,
        prefix=accumulation_prefix,
    )

    if not samples:
        logger.info("No accumulated samples found. Pipeline complete with no action.")
        summary = {
            "status": "completed",
            "total_samples": 0,
            "quality_gate_passed": False,
            "reason": "No accumulated samples",
            "files_cleaned": 0,
        }
        _create_summary_artifact(summary)
        return summary

    # Step 2: Validate quality
    quality_result = validate_accumulation_quality(
        samples=samples,
        existing_data_count=existing_data_count,
        max_pseudo_label_ratio=max_pseudo_label_ratio,
        min_samples=min_samples,
    )

    if not quality_result["passed"]:
        logger.warning(
            "Quality gate failed: %s. Accumulated files will NOT be cleaned up.",
            quality_result["reason"],
        )
        summary = {
            "status": "completed",
            "total_samples": len(samples),
            "quality_gate_passed": False,
            "reason": quality_result["reason"],
            "stats": quality_result.get("stats", {}),
            "files_cleaned": 0,
        }
        _create_summary_artifact(summary)
        return summary

    # Step 3: Cleanup processed files (quality gate passed)
    # Collect unique S3 keys from samples
    s3_keys = list({s.get("_s3_key") for s in samples if s.get("_s3_key")})
    files_cleaned = cleanup_accumulated(
        s3_endpoint=s3_endpoint,
        s3_access_key=s3_access_key,
        s3_secret_key=s3_secret_key,
        bucket=accumulation_bucket,
        prefix=accumulation_prefix,
        keys=s3_keys if s3_keys else None,
    )

    # Trigger continuous training if enabled
    retraining_triggered = False
    if trigger_retraining:
        retraining_triggered = _trigger_retraining()

    summary = {
        "status": "completed",
        "total_samples": len(samples),
        "quality_gate_passed": True,
        "reason": quality_result["reason"],
        "stats": quality_result.get("stats", {}),
        "files_cleaned": files_cleaned,
        "retraining_triggered": retraining_triggered,
    }

    _create_summary_artifact(summary)
    logger.info("Data accumulation pipeline complete: %s", summary)
    return summary


def _create_summary_artifact(summary: dict) -> None:
    """Create a Prefect markdown artifact summarizing the accumulation pipeline run.

    Args:
        summary: Pipeline summary dict with quality gate results.
    """
    gate_status = "PASSED" if summary.get("quality_gate_passed") else "FAILED"
    stats = summary.get("stats", {})

    stats_rows = ""
    for key, value in stats.items():
        if key == "class_distribution":
            value = str(value)
        elif isinstance(value, float):
            value = f"{value:.3f}"
        stats_rows += f"| {key} | {value} |\n"

    markdown = f"""## Data Accumulation Pipeline Summary
| Metric | Value |
|--------|-------|
| Status | {summary.get("status", "unknown")} |
| Total Accumulated Samples | {summary.get("total_samples", 0)} |
| Quality Gate | {gate_status} |
| Reason | {summary.get("reason", "N/A")} |
| Files Cleaned | {summary.get("files_cleaned", 0)} |

### Quality Gate Stats
| Stat | Value |
|------|-------|
{stats_rows}"""
    create_markdown_artifact(key="data-accumulation-summary", markdown=markdown)


def _run_async(coro: Coroutine[object, object, object]) -> object:
    """Run a coroutine from sync context, handling existing event loops.

    Uses ``asyncio.run()`` when no loop is running; otherwise schedules the
    coroutine on the existing loop from a worker thread to avoid
    ``RuntimeError: This event loop is already running``.

    Args:
        coro: Awaitable coroutine to execute.

    Returns:
        The coroutine's return value.
    """
    import asyncio
    import concurrent.futures

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(asyncio.run, coro)
        return future.result(timeout=30)


def _trigger_retraining() -> bool:
    """Trigger the continuous training deployment after successful accumulation.

    Returns:
        True if the deployment was triggered successfully, False otherwise.
    """
    try:
        from prefect.deployments import run_deployment

        from src.core.orchestration.config import ContinuousTrainingConfig

        config = ContinuousTrainingConfig()
        _run_async(
            run_deployment(
                name=config.deployment_name,
                parameters={"trigger_source": "data_accumulated"},
                timeout=0,
            )
        )
        logger.info("Triggered continuous training due to data accumulation.")
        return True
    except Exception:
        logger.warning("Failed to trigger retraining on data accumulation.", exc_info=True)
        return False
