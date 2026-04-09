"""Polling utilities for async service updates."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

import httpx

if TYPE_CHECKING:
    from collections.abc import Callable


def wait_for_condition(
    check_fn: Callable[[], bool],
    timeout: float = 60.0,
    poll_interval: float = 2.0,
    description: str = "condition",
) -> None:
    """Poll check_fn until it returns True or timeout expires.

    Args:
        check_fn: Callable that returns True when condition is met.
        timeout: Maximum time to wait in seconds.
        poll_interval: Seconds between polls.
        description: Human-readable description for error messages.

    Raises:
        TimeoutError: If condition is not met within timeout.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if check_fn():
            return
        time.sleep(poll_interval)
    msg = f"Timed out after {timeout}s waiting for: {description}"
    raise TimeoutError(msg)


def wait_for_prefect_flow_run(
    prefect_base_url: str,
    flow_name: str | None = None,
    timeout: float = 120.0,
    poll_interval: float = 5.0,
) -> dict[str, Any]:
    """Poll Prefect API until a flow run appears (optionally filtered by flow name).

    Args:
        prefect_base_url: Prefect server base URL.
        flow_name: Optional flow name to filter by.
        timeout: Maximum time to wait in seconds.
        poll_interval: Seconds between polls.

    Returns:
        The flow run dict from Prefect API.

    Raises:
        TimeoutError: If no matching flow run found within timeout.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            response = httpx.post(
                f"{prefect_base_url}/api/flow_runs/filter",
                json={"sort": "EXPECTED_START_TIME_DESC", "limit": 5},
                timeout=10.0,
            )
            if response.status_code == 200:
                runs = response.json()
                for run in runs:
                    if flow_name is None or run.get("name", "").startswith(flow_name):
                        return run
        except httpx.RequestError:
            pass
        time.sleep(poll_interval)
    msg = f"No Prefect flow run found within {timeout}s"
    raise TimeoutError(msg)


def wait_for_minio_object(
    s3_client: Any,
    bucket: str,
    prefix: str,
    timeout: float = 60.0,
    poll_interval: float = 3.0,
) -> str:
    """Poll S3/MinIO until at least one object with given prefix exists.

    Args:
        s3_client: boto3 S3 client.
        bucket: Bucket name.
        prefix: Object key prefix to search for.
        timeout: Maximum time to wait in seconds.
        poll_interval: Seconds between polls.

    Returns:
        The key of the first matching object.

    Raises:
        TimeoutError: If no object found within timeout.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            response = s3_client.list_objects_v2(Bucket=bucket, Prefix=prefix, MaxKeys=1)
            contents = response.get("Contents", [])
            if contents:
                return contents[0]["Key"]
        except Exception:
            pass
        time.sleep(poll_interval)
    msg = f"No object found in s3://{bucket}/{prefix} within {timeout}s"
    raise TimeoutError(msg)
