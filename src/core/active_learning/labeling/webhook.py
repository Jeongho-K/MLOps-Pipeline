"""FastAPI webhook router for Label Studio annotation events.

Receives webhook callbacks from Label Studio when annotations are created,
updated, or deleted. Triggers Prefect continuous training flow when
annotation count exceeds the configured threshold.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import time
from typing import Any

from fastapi import APIRouter, HTTPException, Request

logger = logging.getLogger(__name__)

webhook_router = APIRouter(prefix="/webhooks", tags=["webhooks"])

# Debounce state: prevent rapid re-triggers
_last_trigger_time: float = 0.0
_DEBOUNCE_SECONDS: float = 60.0


async def _verify_webhook_signature(request: Request) -> None:
    """Verify Label Studio webhook HMAC-SHA256 signature.

    Skips verification if AL_WEBHOOK_SECRET is not configured.

    Args:
        request: Incoming FastAPI request.

    Raises:
        HTTPException: If signature is missing or invalid.
    """
    secret = os.environ.get("AL_WEBHOOK_SECRET", "")
    if not secret:
        return

    body = await request.body()
    signature = request.headers.get("X-Label-Studio-Signature", "")
    if not signature:
        raise HTTPException(status_code=401, detail="Missing webhook signature")

    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")


@webhook_router.post("/label-studio")
async def handle_label_studio_webhook(
    request: Request,
    payload: dict[str, Any],
) -> dict[str, str]:
    """Handle Label Studio annotation events.

    On ANNOTATION_CREATED, checks if the annotation count exceeds the
    configured threshold and triggers the continuous training flow
    via Prefect's run_deployment API.

    Args:
        request: FastAPI request for signature verification.
        payload: Raw webhook payload from Label Studio.

    Returns:
        Acknowledgment dict with status.
    """
    await _verify_webhook_signature(request)

    action = payload.get("action", "unknown")
    task_id = payload.get("task", {}).get("id") if isinstance(payload.get("task"), dict) else payload.get("task")
    project_raw = payload.get("project")
    project_id = project_raw.get("id") if isinstance(project_raw, dict) else project_raw

    logger.info(
        "Label Studio webhook received: action=%s, task_id=%s, project_id=%s",
        action,
        task_id,
        project_id,
    )

    if action == "ANNOTATION_CREATED":
        await _maybe_trigger_retraining(project_id)

    return {"status": "received"}


async def _maybe_trigger_retraining(project_id: int | None) -> None:
    """Check annotation count and trigger retraining if threshold is met.

    Uses debouncing to prevent rapid re-triggers when multiple
    annotations arrive in quick succession.

    Args:
        project_id: Label Studio project ID.
    """
    global _last_trigger_time  # noqa: PLW0603

    # Debounce check
    now = time.monotonic()
    if now - _last_trigger_time < _DEBOUNCE_SECONDS:
        remaining = _DEBOUNCE_SECONDS - (now - _last_trigger_time)
        logger.debug("Debounce active, skipping trigger check (%.1fs remaining)", remaining)
        return

    try:
        from src.core.orchestration.config import ContinuousTrainingConfig

        config = ContinuousTrainingConfig()

        # Check annotation count
        from src.core.active_learning.labeling.bridge import LabelStudioBridge

        bridge = LabelStudioBridge(
            base_url=config.label_studio_url,
            api_key=config.label_studio_api_key,
            project_id=config.label_studio_project_id,
        )
        try:
            count = bridge.get_annotation_count(project_id)
        finally:
            bridge.close()

        if count < config.min_annotation_count:
            logger.info(
                "Annotation count (%d) below threshold (%d). No trigger.",
                count,
                config.min_annotation_count,
            )
            return

        # Trigger continuous training flow
        logger.info(
            "Annotation count (%d) >= threshold (%d). Triggering continuous training.",
            count,
            config.min_annotation_count,
        )

        from prefect.deployments import run_deployment

        await run_deployment(
            name=config.deployment_name,
            parameters={"trigger_source": "labeling_complete"},
            timeout=0,
        )

        _last_trigger_time = time.monotonic()
        logger.info("Continuous training deployment triggered successfully.")

    except Exception:
        logger.warning("Failed to trigger retraining from webhook.", exc_info=True)
