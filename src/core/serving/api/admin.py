"""Admin API routes for manual operations.

Provides endpoints for manually triggering pipeline operations
such as retraining. Protected by API key authentication.
"""

from __future__ import annotations

import hmac
import logging
import os
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Security
from fastapi.security import APIKeyHeader

logger = logging.getLogger(__name__)

_api_key_header = APIKeyHeader(name="X-Admin-Key", auto_error=False)


async def _verify_admin_key(
    api_key: str | None = Security(_api_key_header),
) -> str:
    """Verify admin API key from request header.

    Args:
        api_key: Value of X-Admin-Key header.

    Returns:
        The validated API key.

    Raises:
        HTTPException: If key is missing or invalid.
    """
    expected = os.environ.get("ADMIN_API_KEY", "")
    if not expected:
        logger.warning("ADMIN_API_KEY not set — admin endpoints are unprotected")
        return ""
    if not api_key or not hmac.compare_digest(api_key, expected):
        raise HTTPException(status_code=403, detail="Invalid or missing admin API key")
    return api_key


admin_router = APIRouter(
    prefix="/admin",
    tags=["admin"],
    dependencies=[Depends(_verify_admin_key)],
)


@admin_router.post("/trigger-retraining")
async def trigger_retraining(
    trigger_source: str = "manual",
    parameters: dict[str, Any] | None = None,
) -> dict[str, str]:
    """Manually trigger the continuous training deployment.

    Args:
        trigger_source: Trigger source label (default: "manual").
        parameters: Additional parameters to pass to the flow.

    Returns:
        Dict with trigger status.
    """
    try:
        from prefect.deployments import run_deployment

        from src.core.orchestration.config import ContinuousTrainingConfig

        config = ContinuousTrainingConfig()

        flow_params: dict[str, Any] = {"trigger_source": trigger_source}
        if parameters:
            flow_params.update(parameters)

        await run_deployment(
            name=config.deployment_name,
            parameters=flow_params,
            timeout=0,
        )

        logger.info("Manual retraining triggered with source=%s", trigger_source)
        return {"status": "triggered", "deployment": config.deployment_name}

    except Exception:
        logger.exception("Failed to trigger retraining manually.")
        raise HTTPException(
            status_code=503,
            detail="Failed to trigger deployment. Check Prefect server.",
        ) from None
