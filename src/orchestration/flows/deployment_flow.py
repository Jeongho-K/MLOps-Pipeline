"""Canary deployment flow (Phase C).

Orchestrates the canary deployment lifecycle:
start canary → health check → nginx weight split → G4 monitoring loop →
full rollout or rollback.
"""

from __future__ import annotations

import logging
import time

from prefect import flow
from prefect.artifacts import create_markdown_artifact

from src.orchestration.config_deployment import DeploymentConfig
from src.orchestration.tasks.canary_gate import check_canary_gate
from src.orchestration.tasks.deployment_tasks import (
    reload_champion_model,
    start_canary_container,
    stop_canary_container,
    update_nginx_weights,
    wait_for_canary_health,
)

logger = logging.getLogger(__name__)


@flow(
    name="canary-deployment",
    log_prints=True,
    retries=0,
    description=(
        "Phase C canary deployment: start canary container → Nginx weight split → "
        "G4 monitoring → full rollout or rollback"
    ),
)
def deployment_flow(
    trigger_source: str = "champion_promotion",
    # Override defaults via DeploymentConfig or direct params
    canary_duration_minutes: int | None = None,
    canary_check_interval_seconds: int | None = None,
    canary_weight: int | None = None,
    champion_weight: int | None = None,
    max_error_rate_ratio: float | None = None,
    max_latency_ratio: float | None = None,
    absolute_max_error_rate: float | None = None,
) -> dict:
    """Run the canary deployment pipeline.

    Args:
        trigger_source: What triggered this deployment.
        canary_duration_minutes: Override monitoring duration.
        canary_check_interval_seconds: Override check interval.
        canary_weight: Override Nginx canary weight.
        champion_weight: Override Nginx champion weight.
        max_error_rate_ratio: Override G4 error rate threshold.
        max_latency_ratio: Override G4 latency threshold.
        absolute_max_error_rate: Override G4 absolute error ceiling.

    Returns:
        Dictionary summarizing the deployment result.
    """
    config = DeploymentConfig()

    # Apply overrides (use 'is not None' to allow explicit 0 / 0.0 values)
    duration = canary_duration_minutes if canary_duration_minutes is not None else config.canary_duration_minutes
    interval = (
        canary_check_interval_seconds
        if canary_check_interval_seconds is not None
        else config.canary_check_interval_seconds
    )
    c_weight = canary_weight if canary_weight is not None else config.canary_weight
    ch_weight = champion_weight if champion_weight is not None else config.champion_weight
    err_ratio = max_error_rate_ratio if max_error_rate_ratio is not None else config.max_error_rate_ratio
    lat_ratio = max_latency_ratio if max_latency_ratio is not None else config.max_latency_ratio
    abs_err = absolute_max_error_rate if absolute_max_error_rate is not None else config.absolute_max_error_rate

    logger.info(
        "Starting canary deployment (trigger=%s, duration=%dm, weights=%d:%d)",
        trigger_source,
        duration,
        ch_weight,
        c_weight,
    )

    # Step 1: Start canary container
    start_canary_container(project_name=config.docker_compose_project)

    # Step 2: Wait for canary to be healthy
    wait_for_canary_health(health_url=config.canary_health_url)

    # Step 3: Update Nginx weights (split traffic)
    update_nginx_weights(
        champion_weight=ch_weight,
        canary_weight=c_weight,
        nginx_container=config.nginx_container_name,
        upstream_path=config.nginx_upstream_path,
    )

    # Step 4: G4 Canary Gate monitoring loop
    passed = _run_canary_monitoring(
        config=config,
        duration_minutes=duration,
        interval_seconds=interval,
        max_error_rate_ratio=err_ratio,
        max_latency_ratio=lat_ratio,
        absolute_max_error_rate=abs_err,
    )

    # Step 5/6: Rollout or rollback
    result = _full_rollout(config) if passed else _rollback(config)

    result["trigger_source"] = trigger_source
    _create_deployment_artifact(result)
    return result


def _run_canary_monitoring(
    config: DeploymentConfig,
    duration_minutes: int,
    interval_seconds: int,
    max_error_rate_ratio: float,
    max_latency_ratio: float,
    absolute_max_error_rate: float,
) -> bool:
    """Run the G4 canary monitoring loop.

    Args:
        config: Deployment configuration.
        duration_minutes: Total monitoring duration.
        interval_seconds: Seconds between each G4 check.
        max_error_rate_ratio: G4 error rate threshold.
        max_latency_ratio: G4 latency threshold.
        absolute_max_error_rate: G4 absolute error ceiling.

    Returns:
        True if all checks passed, False if any check failed.
    """
    total_seconds = duration_minutes * 60
    checks_total = max(1, total_seconds // interval_seconds)

    logger.info(
        "G4 monitoring: %d checks over %d minutes (every %ds)",
        checks_total,
        duration_minutes,
        interval_seconds,
    )

    for i in range(checks_total):
        if i > 0:
            time.sleep(interval_seconds)

        logger.info("G4 check %d/%d", i + 1, checks_total)

        g4_result = check_canary_gate(
            prometheus_url=config.prometheus_url,
            max_error_rate_ratio=max_error_rate_ratio,
            max_latency_ratio=max_latency_ratio,
            absolute_max_error_rate=absolute_max_error_rate,
        )

        if not g4_result["passed"]:
            logger.warning(
                "G4 check %d/%d FAILED: %s",
                i + 1,
                checks_total,
                g4_result["reason"],
            )
            return False

    logger.info("All %d G4 checks passed", checks_total)
    return True


def _full_rollout(config: DeploymentConfig) -> dict:
    """Execute full rollout: champion reloads new model, canary removed.

    Args:
        config: Deployment configuration.

    Returns:
        Rollout result dict.
    """
    logger.info("G4 passed — executing full rollout")

    # Remove canary from Nginx upstream
    update_nginx_weights(
        champion_weight=10,
        canary_weight=0,
        nginx_container=config.nginx_container_name,
        upstream_path=config.nginx_upstream_path,
    )

    # Reload champion model (it now points to the newly promoted @champion)
    reload_champion_model(reload_url=config.champion_reload_url)

    # Stop canary container
    stop_canary_container(project_name=config.docker_compose_project)

    return {"status": "rolled_out", "action": "full_rollout"}


def _rollback(config: DeploymentConfig) -> dict:
    """Execute rollback: restore champion-only config, stop canary.

    Args:
        config: Deployment configuration.

    Returns:
        Rollback result dict.
    """
    logger.warning("G4 failed — executing rollback")

    # Restore champion-only Nginx upstream
    update_nginx_weights(
        champion_weight=10,
        canary_weight=0,
        nginx_container=config.nginx_container_name,
        upstream_path=config.nginx_upstream_path,
    )

    # Stop canary container
    stop_canary_container(project_name=config.docker_compose_project)

    return {"status": "rolled_back", "action": "rollback"}


def _create_deployment_artifact(result: dict) -> None:
    """Create a Prefect markdown artifact summarizing the deployment.

    Args:
        result: Deployment result dict.
    """
    status = result.get("status", "unknown")
    action = result.get("action", "unknown")
    trigger = result.get("trigger_source", "unknown")

    icon = "✅" if status == "rolled_out" else "⚠️"

    markdown = f"""## Canary Deployment — {icon} {status.replace("_", " ").title()}

**Trigger:** {trigger} | **Action:** {action}
"""
    create_markdown_artifact(key="canary-deployment", markdown=markdown)
