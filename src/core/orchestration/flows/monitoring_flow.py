"""Daily drift monitoring pipeline flow.

Orchestrates: fetch prediction logs → fetch reference data →
run drift detection → upload drift report.
"""

from __future__ import annotations

import logging
import os
import tempfile
from datetime import date, timedelta
from typing import Any

import boto3
import pandas as pd
from prefect import flow, task
from prefect.artifacts import create_markdown_artifact

from src.core.monitoring.evidently.config import DriftConfig
from src.core.monitoring.evidently.drift_detector import (
    build_dataframe_from_logs,
    check_drift_threshold,
    detect_drift,
    push_drift_metrics,
    save_drift_report_html,
)

logger = logging.getLogger(__name__)


@task(name="fetch-prediction-logs", retries=2, retry_delay_seconds=30)
def fetch_prediction_logs(
    s3_endpoint: str,
    bucket: str,
    access_key: str,
    secret_key: str,
    lookback_days: int = 1,
) -> pd.DataFrame:
    """Fetch prediction logs from S3 for each day in the lookback window.

    Lists objects under ``{YYYY-MM-DD}/`` prefixes for each day in the
    lookback window, concatenates all JSONL file contents, and returns
    a single DataFrame.

    Args:
        s3_endpoint: S3-compatible endpoint URL (e.g. ``http://minio:9000``).
        bucket: S3 bucket name containing prediction logs.
        access_key: AWS/MinIO access key ID.
        secret_key: AWS/MinIO secret access key.
        lookback_days: Number of past days to fetch logs for.

    Returns:
        DataFrame constructed from all fetched JSONL records.
        Returns an empty DataFrame if no logs are found.
    """
    client = boto3.client(
        "s3",
        endpoint_url=s3_endpoint,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
    )

    today = date.today()
    all_jsonl: list[str] = []

    for offset in range(lookback_days):
        day = today - timedelta(days=offset)
        prefix = f"{day.isoformat()}/"

        response = client.list_objects_v2(Bucket=bucket, Prefix=prefix)
        objects = response.get("Contents", [])

        for obj in objects:
            key = obj["Key"]
            if not key.endswith(".jsonl"):
                continue
            body = client.get_object(Bucket=bucket, Key=key)["Body"].read()
            all_jsonl.append(body.decode("utf-8"))

    if not all_jsonl:
        logger.info("No prediction logs found for the last %d day(s).", lookback_days)
        return pd.DataFrame()

    combined = "\n".join(all_jsonl)
    df = build_dataframe_from_logs(combined)
    logger.info("Fetched %d prediction log records.", len(df))
    return df


@task(name="fetch-reference-data", retries=2, retry_delay_seconds=30)
def fetch_reference_data(
    s3_endpoint: str,
    bucket: str,
    access_key: str,
    secret_key: str,
    reference_path: str,
) -> pd.DataFrame:
    """Fetch the reference (baseline) dataset from S3.

    Args:
        s3_endpoint: S3-compatible endpoint URL.
        bucket: S3 bucket name containing the reference data.
        access_key: AWS/MinIO access key ID.
        secret_key: AWS/MinIO secret access key.
        reference_path: S3 object key for the reference JSONL file.

    Returns:
        DataFrame constructed from the reference JSONL file.
        Returns an empty DataFrame if the file is empty.
    """
    client = boto3.client(
        "s3",
        endpoint_url=s3_endpoint,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
    )

    body = client.get_object(Bucket=bucket, Key=reference_path)["Body"].read()
    raw_jsonl = body.decode("utf-8")
    df = build_dataframe_from_logs(raw_jsonl)
    logger.info("Fetched %d reference records from s3://%s/%s.", len(df), bucket, reference_path)
    return df


@task(name="run-drift-detection")
def run_drift_detection(
    reference: pd.DataFrame,
    current: pd.DataFrame,
    pushgateway_url: str,
) -> dict[str, Any]:
    """Run Evidently drift detection and push results to Prometheus Pushgateway.

    Args:
        reference: Reference (baseline) DataFrame.
        current: Current (production) DataFrame.
        pushgateway_url: URL of the Prometheus Pushgateway.

    Returns:
        Dictionary with keys ``drift_detected`` (bool), ``drift_score`` (float),
        and ``column_drifts`` (dict[str, float]).
    """
    result = detect_drift(reference, current)
    push_drift_metrics(
        pushgateway_url=pushgateway_url,
        drift_detected=result["drift_detected"],
        drift_score=result["drift_score"],
        column_drifts=result.get("column_drifts"),
    )

    # Create Prefect artifact for drift detection results
    column_rows = ""
    for col, score in result.get("column_drifts", {}).items():
        column_rows += f"| {col} | {score:.4f} |\n"

    status_emoji = "DRIFT DETECTED" if result["drift_detected"] else "No Drift"
    markdown = f"""## Drift Detection Results: {status_emoji}
| Metric | Value |
|--------|-------|
| Drift Detected | {result["drift_detected"]} |
| Drift Score | {result["drift_score"]:.4f} |

### Per-Column Drift Scores
| Column | Score |
|--------|-------|
{column_rows}"""
    create_markdown_artifact(key="drift-detection-results", markdown=markdown)

    return result


@task(name="run-drift-quality-gate")
def run_drift_quality_gate(
    reference: pd.DataFrame,
    current: pd.DataFrame,
    drift_share_threshold: float = 0.3,
) -> dict[str, Any]:
    """Run drift threshold check as a quality gate.

    Args:
        reference: Reference (baseline) DataFrame.
        current: Current (production) DataFrame.
        drift_share_threshold: Maximum acceptable share of drifted columns.

    Returns:
        Dictionary with drift threshold check results.

    Raises:
        RuntimeError: If drift exceeds threshold.
    """
    result = check_drift_threshold(reference, current, drift_share_threshold)

    status = "PASSED" if result["passed"] else "FAILED"
    column_rows = ""
    for col, score in result.get("column_drifts", {}).items():
        column_rows += f"| {col} | {score:.4f} |\n"

    markdown = f"""## Drift Quality Gate: {status}
| Metric | Value |
|--------|-------|
| Drift Score | {result["drift_score"]:.4f} |
| Threshold | {result["threshold"]:.4f} |
| Result | {status} |

### Per-Column Drift
| Column | Score |
|--------|-------|
{column_rows}"""
    create_markdown_artifact(key="drift-quality-gate", markdown=markdown)

    if not result["passed"]:
        raise RuntimeError(
            f"Drift quality gate failed: drift_score={result['drift_score']:.4f} "
            f"exceeds threshold={drift_share_threshold:.4f}"
        )

    return result


@task(name="upload-drift-report", retries=2, retry_delay_seconds=30)
def upload_drift_report(
    reference: pd.DataFrame,
    current: pd.DataFrame,
    s3_endpoint: str,
    bucket: str,
    access_key: str,
    secret_key: str,
) -> str:
    """Generate an HTML drift report and upload it to S3.

    Writes the report to a temporary file, uploads it to S3 under
    ``{YYYY-MM-DD}/drift-report.html``, and returns the S3 key.

    Args:
        reference: Reference (baseline) DataFrame.
        current: Current (production) DataFrame.
        s3_endpoint: S3-compatible endpoint URL.
        bucket: S3 bucket name for drift reports.
        access_key: AWS/MinIO access key ID.
        secret_key: AWS/MinIO secret access key.

    Returns:
        S3 object key of the uploaded report.
    """
    client = boto3.client(
        "s3",
        endpoint_url=s3_endpoint,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
    )

    today = date.today()
    s3_key = f"{today.isoformat()}/drift-report.html"

    fd, tmp_path = tempfile.mkstemp(suffix=".html")
    os.close(fd)
    try:
        save_drift_report_html(reference, current, tmp_path)
        client.upload_file(tmp_path, bucket, s3_key)
        logger.info("Drift report uploaded to s3://%s/%s", bucket, s3_key)
    finally:
        os.unlink(tmp_path)
    return s3_key


@flow(
    name="monitoring-pipeline",
    retries=0,
    description="Daily drift monitoring: fetch logs → detect drift → upload report",
)
def monitoring_pipeline(
    s3_endpoint: str | None = None,
    s3_access_key: str | None = None,
    s3_secret_key: str | None = None,
    prediction_logs_bucket: str | None = None,
    drift_reports_bucket: str | None = None,
    reference_path: str | None = None,
    lookback_days: int | None = None,
    pushgateway_url: str | None = None,
    fail_on_drift: bool = False,
    trigger_retraining_on_drift: bool = True,
) -> dict[str, Any]:
    """Run the full drift monitoring pipeline.

    All parameters default to values from DriftConfig (DRIFT_ env prefix).

    Steps:
        1. Fetch prediction logs from S3 for the lookback window.
        2. Fetch reference (baseline) data from S3.
        3. Filter both DataFrames to common columns.
        4. Run Evidently drift detection and push metrics to Pushgateway.
        4.5. Run drift quality gate (pass/fail test based on threshold).
        5. Generate and upload an HTML drift report to S3.

    Args:
        s3_endpoint: S3-compatible endpoint URL.
        s3_access_key: AWS/MinIO access key ID.
        s3_secret_key: AWS/MinIO secret access key.
        prediction_logs_bucket: Bucket containing prediction logs.
        drift_reports_bucket: Bucket for storing drift reports.
        reference_path: S3 key of the reference JSONL file.
        lookback_days: Number of past days to include in current data.
        pushgateway_url: URL of the Prometheus Pushgateway.
        fail_on_drift: If True, raise RuntimeError when drift exceeds threshold.
            Defaults to False (log warning and continue).
        trigger_retraining_on_drift: If True, trigger continuous training
            deployment when drift is detected. Defaults to True.

    Returns:
        Dictionary with drift detection results and the uploaded report S3 key.
        Returns ``{"status": "skipped", "reason": ...}`` if data is insufficient.
    """
    cfg = DriftConfig()
    s3_endpoint = s3_endpoint or cfg.s3_endpoint
    s3_access_key = s3_access_key or cfg.s3_access_key
    s3_secret_key = s3_secret_key or cfg.s3_secret_key
    prediction_logs_bucket = prediction_logs_bucket or cfg.prediction_logs_bucket
    drift_reports_bucket = drift_reports_bucket or cfg.drift_reports_bucket
    reference_path = reference_path or cfg.reference_path
    lookback_days = lookback_days or cfg.lookback_days
    pushgateway_url = pushgateway_url or cfg.pushgateway_url

    # Step 1: Fetch prediction logs
    current_df = fetch_prediction_logs(
        s3_endpoint=s3_endpoint,
        bucket=prediction_logs_bucket,
        access_key=s3_access_key,
        secret_key=s3_secret_key,
        lookback_days=lookback_days,
    )
    if current_df.empty:
        logger.warning("No prediction logs found; skipping monitoring pipeline.")
        return {"status": "skipped", "reason": "no prediction logs"}

    # Step 2: Fetch reference data
    reference_df = fetch_reference_data(
        s3_endpoint=s3_endpoint,
        bucket=prediction_logs_bucket,
        access_key=s3_access_key,
        secret_key=s3_secret_key,
        reference_path=reference_path,
    )
    if reference_df.empty:
        logger.warning("Reference data is empty; skipping monitoring pipeline.")
        return {"status": "skipped", "reason": "empty reference data"}

    # Step 3: Filter to common columns
    desired_cols = {"predicted_class", "confidence"}
    shared_cols = sorted(desired_cols & set(current_df.columns) & set(reference_df.columns))

    if not shared_cols:
        logger.warning(
            "No shared columns (%s) between reference and current data; skipping.",
            desired_cols,
        )
        return {"status": "skipped", "reason": "no shared columns"}

    current_filtered = current_df[shared_cols]
    reference_filtered = reference_df[shared_cols]

    # Step 4: Run drift detection
    drift_result = run_drift_detection(
        reference=reference_filtered,
        current=current_filtered,
        pushgateway_url=pushgateway_url,
    )

    # Step 4.5: Run drift quality gate (pass/fail based on threshold)
    drift_gate_failed = False
    try:
        gate_result = run_drift_quality_gate(
            reference=reference_filtered,
            current=current_filtered,
        )
        logger.info("Drift quality gate passed: %s", gate_result)
    except RuntimeError:
        drift_gate_failed = True
        if fail_on_drift:
            raise
        logger.warning("Drift quality gate failed — continuing with report upload.", exc_info=True)

    # Step 5: Upload drift report
    report_key = upload_drift_report(
        reference=reference_filtered,
        current=current_filtered,
        s3_endpoint=s3_endpoint,
        bucket=drift_reports_bucket,
        access_key=s3_access_key,
        secret_key=s3_secret_key,
    )

    # Step 6: G5 Runtime Gate — severity-based auto-response
    g5_result: dict[str, Any] = {}
    if drift_gate_failed:
        from src.core.orchestration.tasks.runtime_gate import evaluate_runtime_gate

        g5_result = evaluate_runtime_gate(
            drift_score=drift_result.get("drift_score", 0.0),
            drift_detected=drift_result.get("drift_detected", False),
        )

        if g5_result["action"] == "rollback_and_retrain":
            logger.warning("G5 HIGH severity — triggering rollback and retraining")
            _trigger_rollback()
            if trigger_retraining_on_drift:
                _trigger_retraining_on_drift()
        elif g5_result["action"] == "trigger_active_learning":
            logger.info("G5 MEDIUM severity — triggering AL pipeline and retraining")
            _trigger_active_learning_pipeline()
            if trigger_retraining_on_drift:
                _trigger_retraining_on_drift()
        else:
            logger.info("G5 LOW severity — logging only, no action taken")

    result: dict[str, Any] = {
        **drift_result,
        "report_s3_key": report_key,
        "g5_result": g5_result,
        "status": "completed",
    }
    logger.info("Monitoring pipeline complete: %s", result)
    return result


def _trigger_retraining_on_drift() -> None:
    """Trigger the continuous training deployment when drift is detected.

    Best-effort: logs warning if triggering fails (e.g. deployment not registered).
    """
    try:
        from prefect.deployments import run_deployment

        from src.core.orchestration.config import ContinuousTrainingConfig

        config = ContinuousTrainingConfig()
        run_deployment(
            name=config.deployment_name,
            parameters={"trigger_source": "drift_detected"},
            timeout=0,
        )
        logger.info("Triggered continuous training due to drift detection.")
    except Exception:
        logger.warning("Failed to trigger retraining on drift.", exc_info=True)


def _trigger_rollback() -> None:
    """Request the champion container to reload its current model.

    This forces the serving container to re-fetch the @champion model
    artifact from MLflow, which acts as a safety reload. A full version
    rollback (reverting the @champion alias to a prior version) is not
    yet implemented and would require MLflow alias management.

    Best-effort: logs warning if the reload request fails.
    """
    try:
        import httpx

        from src.core.orchestration.config_deployment import DeploymentConfig

        config = DeploymentConfig()
        response = httpx.post(config.champion_reload_url, timeout=60.0)
        response.raise_for_status()
        logger.info("Rollback triggered: champion model reload requested.")
    except Exception:
        logger.warning("Failed to trigger rollback.", exc_info=True)


def _trigger_active_learning_pipeline() -> None:
    """Trigger the active learning pipeline to increase data collection.

    Best-effort: logs warning if triggering fails.
    """
    try:
        from prefect.deployments import run_deployment

        run_deployment(
            name="active-learning-pipeline/active-learning-deployment",
            parameters={"trigger_source": "g5_medium_drift"},
            timeout=0,
        )
        logger.info("Triggered active learning pipeline due to medium drift.")
    except Exception:
        logger.warning("Failed to trigger active learning pipeline.", exc_info=True)
