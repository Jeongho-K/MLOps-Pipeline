"""Deployment tasks for canary lifecycle management.

Manages Docker container lifecycle, Nginx configuration updates,
and model reload during canary deployments.
"""

from __future__ import annotations

import logging
import subprocess
import tempfile
import time
from pathlib import Path

import httpx
from prefect import task

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_CANARY_TEMPLATE_PATH = _PROJECT_ROOT / "configs" / "nginx" / "canary.conf.template"
_DEFAULT_UPSTREAM_TEMPLATE = "upstream api_backend {\n    server api:8000;\n}\n"


@task(name="start-canary-container", retries=1, retry_delay_seconds=10)
def start_canary_container(
    project_name: str = "data-flywheel",
) -> None:
    """Start the api-canary container via Docker Compose.

    Args:
        project_name: Docker Compose project name.
    """
    logger.info("Starting canary container...")
    result = subprocess.run(
        [
            "docker",
            "compose",
            "-p",
            project_name,
            "--profile",
            "canary",
            "up",
            "-d",
            "api-canary",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        logger.error("Failed to start canary: %s", result.stderr)
        raise RuntimeError(f"Failed to start canary container: {result.stderr}")
    logger.info("Canary container started")


@task(name="wait-for-canary-health", retries=0)
def wait_for_canary_health(
    health_url: str = "http://localhost:8000/health",
    timeout_seconds: int = 120,
    poll_interval: int = 5,
) -> None:
    """Poll canary health endpoint until it responds successfully.

    Args:
        health_url: URL of the canary health endpoint.
        timeout_seconds: Max seconds to wait for healthy response.
        poll_interval: Seconds between health check attempts.

    Raises:
        TimeoutError: If canary doesn't become healthy within timeout.
    """
    logger.info("Waiting for canary health at %s...", health_url)
    deadline = time.monotonic() + timeout_seconds

    while time.monotonic() < deadline:
        try:
            resp = httpx.get(health_url, timeout=5.0)
            if resp.status_code == 200:
                logger.info("Canary is healthy")
                return
        except httpx.HTTPError:
            pass
        time.sleep(poll_interval)

    raise TimeoutError(
        f"Canary did not become healthy within {timeout_seconds}s"
    )


@task(name="update-nginx-weights")
def update_nginx_weights(
    champion_weight: int,
    canary_weight: int,
    nginx_container: str = "nginx",
    upstream_path: str = "/etc/nginx/conf.d/upstream.conf",
) -> None:
    """Generate Nginx upstream config with specified weights and reload.

    Args:
        champion_weight: Weight for the champion (api) upstream.
        canary_weight: Weight for the canary (api-canary) upstream.
            Set to 0 to remove canary from the upstream.
        nginx_container: Name of the Nginx container.
        upstream_path: Path to the upstream config inside the container.
    """
    if canary_weight > 0:
        template = _CANARY_TEMPLATE_PATH.read_text()
        config = template.format(
            champion_weight=champion_weight,
            canary_weight=canary_weight,
        )
    else:
        config = _DEFAULT_UPSTREAM_TEMPLATE

    logger.info(
        "Updating Nginx weights: champion=%d, canary=%d",
        champion_weight,
        canary_weight,
    )

    # Write config to a temp file and copy into container
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".conf", delete=False
    ) as tmp:
        tmp.write(config)
        tmp_path = tmp.name

    try:
        _run_cmd(
            ["docker", "cp", tmp_path, f"{nginx_container}:{upstream_path}"],
            "copy upstream config",
        )
        _run_cmd(
            ["docker", "exec", nginx_container, "nginx", "-s", "reload"],
            "reload nginx",
        )
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    logger.info("Nginx configuration updated and reloaded")


@task(name="reload-champion-model", retries=2, retry_delay_seconds=10)
def reload_champion_model(
    reload_url: str = "http://localhost:8000/model/reload",
) -> None:
    """Trigger model reload on the champion API container.

    After canary passes, the champion container needs to reload
    the newly promoted @champion model version.

    Args:
        reload_url: URL of the model reload endpoint.
    """
    logger.info("Triggering champion model reload at %s", reload_url)
    response = httpx.post(reload_url, timeout=60.0)
    response.raise_for_status()
    logger.info("Champion model reload triggered successfully")


@task(name="stop-canary-container")
def stop_canary_container(
    project_name: str = "data-flywheel",
) -> None:
    """Stop and remove the api-canary container.

    Args:
        project_name: Docker Compose project name.
    """
    logger.info("Stopping canary container...")
    result = subprocess.run(
        [
            "docker",
            "compose",
            "-p",
            project_name,
            "--profile",
            "canary",
            "stop",
            "api-canary",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        logger.warning("Failed to stop canary (may already be stopped): %s", result.stderr)
    else:
        logger.info("Canary container stopped")


def _run_cmd(cmd: list[str], description: str) -> None:
    """Run a shell command, raising on failure.

    Args:
        cmd: Command and arguments.
        description: Human-readable description for error messages.
    """
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"Failed to {description}: {result.stderr}")
