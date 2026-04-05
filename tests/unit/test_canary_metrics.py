"""Unit tests for canary Prometheus query helpers."""

from __future__ import annotations

from unittest.mock import patch

import httpx

from src.core.monitoring.canary_metrics import (
    _query_prometheus,
    query_error_rate,
    query_p99_latency,
)


def _make_prom_response(value: float) -> dict:
    """Build a mock Prometheus instant query response."""
    return {
        "status": "success",
        "data": {
            "resultType": "vector",
            "result": [{"metric": {}, "value": [1234567890, str(value)]}],
        },
    }


def _make_empty_response() -> dict:
    """Build a mock Prometheus response with no results."""
    return {
        "status": "success",
        "data": {"resultType": "vector", "result": []},
    }


def _mock_response(status_code: int, json_data: dict) -> httpx.Response:
    """Create a mock httpx.Response with a request set (needed for raise_for_status)."""
    request = httpx.Request("GET", "http://test/api/v1/query")
    return httpx.Response(status_code, json=json_data, request=request)


class TestQueryPrometheus:
    """Tests for the internal _query_prometheus function."""

    @patch("src.core.monitoring.canary_metrics.httpx.get")
    def test_returns_value_on_success(self, mock_get: object) -> None:
        mock_get.return_value = _mock_response(200, _make_prom_response(0.02))  # type: ignore[attr-defined]

        result = _query_prometheus("http://prometheus:9090", "up")
        assert result == 0.02

    @patch("src.core.monitoring.canary_metrics.httpx.get")
    def test_returns_none_on_empty_result(self, mock_get: object) -> None:
        mock_get.return_value = _mock_response(200, _make_empty_response())  # type: ignore[attr-defined]

        result = _query_prometheus("http://prometheus:9090", "up")
        assert result is None

    @patch("src.core.monitoring.canary_metrics.httpx.get")
    def test_returns_none_on_http_error(self, mock_get: object) -> None:
        mock_get.side_effect = httpx.ConnectError("connection refused")  # type: ignore[attr-defined]

        result = _query_prometheus("http://prometheus:9090", "up")
        assert result is None

    @patch("src.core.monitoring.canary_metrics.httpx.get")
    def test_returns_none_on_error_status(self, mock_get: object) -> None:
        error_response = {"status": "error", "error": "bad query"}
        mock_get.return_value = _mock_response(200, error_response)  # type: ignore[attr-defined]

        result = _query_prometheus("http://prometheus:9090", "bad")
        assert result is None


class TestQueryErrorRate:
    """Tests for query_error_rate."""

    @patch("src.core.monitoring.canary_metrics._query_prometheus")
    def test_constructs_correct_query(self, mock_query: object) -> None:
        mock_query.return_value = 0.01  # type: ignore[attr-defined]

        result = query_error_rate("http://prom:9090", "api-canary", "5m")
        assert result == 0.01

        call_args = mock_query.call_args  # type: ignore[attr-defined]
        query_str = call_args[0][1]
        assert 'job="api-canary"' in query_str
        assert "5xx" not in query_str  # uses status=~"5.."
        assert '5.."' in query_str

    @patch("src.core.monitoring.canary_metrics._query_prometheus")
    def test_returns_none_when_no_data(self, mock_query: object) -> None:
        mock_query.return_value = None  # type: ignore[attr-defined]
        result = query_error_rate("http://prom:9090", "api")
        assert result is None


class TestQueryP99Latency:
    """Tests for query_p99_latency."""

    @patch("src.core.monitoring.canary_metrics._query_prometheus")
    def test_constructs_histogram_quantile_query(self, mock_query: object) -> None:
        mock_query.return_value = 0.15  # type: ignore[attr-defined]

        result = query_p99_latency("http://prom:9090", "api", "10m")
        assert result == 0.15

        call_args = mock_query.call_args  # type: ignore[attr-defined]
        query_str = call_args[0][1]
        assert "histogram_quantile(0.99" in query_str
        assert 'job="api"' in query_str
        assert "10m" in query_str
