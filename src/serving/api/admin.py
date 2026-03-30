"""Admin API routes for manual operations.

Provides endpoints for manually triggering pipeline operations
such as retraining.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException

logger = logging.getLogger(__name__)

admin_router = APIRouter(prefix="/admin", tags=["admin"])


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

        from src.orchestration.config import ContinuousTrainingConfig

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
