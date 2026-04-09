"""Prometheus query helpers for canary deployment metrics.

Queries Prometheus HTTP API to compare champion and canary
container performance during G4 canary gate evaluation.
"""

from __future__ import annotations

import logging
import math

import httpx

logger = logging.getLogger(__name__)

_QUERY_TIMEOUT = 10.0


def _query_prometheus(prometheus_url: str, query: str) -> float | None:
    """Execute a PromQL instant query and return the scalar result.

    Args:
        prometheus_url: Base URL of the Prometheus server.
        query: PromQL query string.

    Returns:
        The numeric result, or None if no data is available.
    """
    try:
        response = httpx.get(
            f"{prometheus_url}/api/v1/query",
            params={"query": query},
            timeout=_QUERY_TIMEOUT,
        )
        response.raise_for_status()
        data = response.json()

        if data["status"] != "success":
            logger.warning("Prometheus query failed: %s", data.get("error", "unknown"))
            return None

        results = data["data"]["result"]
        if not results:
            return None

        # Instant query returns vector; take first result's value
        value = float(results[0]["value"][1])
        if math.isnan(value) or math.isinf(value):
            logger.warning("Prometheus returned non-finite value: %s", value)
            return None
        return value

    except httpx.HTTPError:
        logger.exception("Failed to query Prometheus at %s", prometheus_url)
        return None
    except (KeyError, IndexError, ValueError):
        logger.exception("Unexpected Prometheus response format")
        return None


def query_error_rate(
    prometheus_url: str,
    job: str,
    window: str = "5m",
) -> float | None:
    """Query the HTTP 5xx error rate for a given job.

    Args:
        prometheus_url: Base URL of the Prometheus server.
        job: Prometheus job name (e.g., "api" or "api-canary").
        window: PromQL time window for rate calculation.

    Returns:
        Error rate as a float (0.0 to 1.0), or None if insufficient data.
    """
    # prometheus-fastapi-instrumentator with should_group_status_codes=True
    # emits status="5xx" (not individual codes like "500", "502")
    query = (
        f'sum(rate(http_requests_total{{job="{job}",status="5xx"}}[{window}]))'
        f" / "
        f'sum(rate(http_requests_total{{job="{job}"}}[{window}]))'
    )
    return _query_prometheus(prometheus_url, query)


def query_p99_latency(
    prometheus_url: str,
    job: str,
    window: str = "5m",
) -> float | None:
    """Query P99 latency (in seconds) for a given job.

    Args:
        prometheus_url: Base URL of the Prometheus server.
        job: Prometheus job name (e.g., "api" or "api-canary").
        window: PromQL time window for rate calculation.

    Returns:
        P99 latency in seconds, or None if insufficient data.
    """
    query = (
        f'histogram_quantile(0.99, sum(rate(http_request_duration_seconds_bucket{{job="{job}"}}[{window}])) by (le))'
    )
    return _query_prometheus(prometheus_url, query)
