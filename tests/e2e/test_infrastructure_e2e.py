"""E2E tests for infrastructure services.

Validates that all Docker services are healthy, databases are initialized,
and S3 buckets exist with versioning enabled.
"""

from __future__ import annotations

import json
import urllib.request


class TestServiceHealth:
    """Verify all services respond to health checks."""

    def test_mlflow_health(self, mlflow_base_url) -> None:
        """MLflow server should be reachable."""
        response = urllib.request.urlopen(f"{mlflow_base_url}/health")
        assert response.status == 200

    def test_prefect_health(self, prefect_base_url) -> None:
        """Prefect server should be reachable."""
        response = urllib.request.urlopen(f"{prefect_base_url}/api/health")
        assert response.status == 200

    def test_prometheus_health(self, prometheus_base_url) -> None:
        """Prometheus should be reachable."""
        response = urllib.request.urlopen(f"{prometheus_base_url}/-/healthy")
        assert response.status == 200

    def test_pushgateway_health(self, pushgateway_base_url) -> None:
        """Pushgateway should be reachable."""
        response = urllib.request.urlopen(f"{pushgateway_base_url}/-/healthy")
        assert response.status == 200

    def test_grafana_health(self, grafana_base_url) -> None:
        """Grafana should be reachable."""
        response = urllib.request.urlopen(f"{grafana_base_url}/api/health")
        data = json.loads(response.read())
        assert data.get("database") == "ok"

    def test_api_health(self, api_base_url) -> None:
        """Inference API should be reachable."""
        response = urllib.request.urlopen(f"{api_base_url}/health")
        data = json.loads(response.read())
        assert "model_loaded" in data

    def test_nginx_health(self, nginx_base_url) -> None:
        """Nginx reverse proxy should be reachable."""
        response = urllib.request.urlopen(f"{nginx_base_url}/nginx/health")
        assert response.status == 200


class TestMinioBuckets:
    """Verify MinIO buckets exist with versioning enabled."""

    EXPECTED_BUCKETS = [
        "mlflow-artifacts",
        "dvc-storage",
        "model-registry",
        "prediction-logs",
        "drift-reports",
    ]

    def test_all_buckets_exist(self, minio_s3_client) -> None:
        """All required S3 buckets should exist."""
        response = minio_s3_client.list_buckets()
        existing = {b["Name"] for b in response["Buckets"]}
        for bucket in self.EXPECTED_BUCKETS:
            assert bucket in existing, f"Bucket '{bucket}' not found"

    def test_buckets_have_versioning(self, minio_s3_client) -> None:
        """All buckets should have versioning enabled."""
        for bucket in self.EXPECTED_BUCKETS:
            response = minio_s3_client.get_bucket_versioning(Bucket=bucket)
            assert response.get("Status") == "Enabled", f"Bucket '{bucket}' versioning is not enabled"


class TestPrometheusTargets:
    """Verify Prometheus is scraping expected targets."""

    def test_api_target_is_scraped(self, prometheus_base_url) -> None:
        """Prometheus should have the API target configured."""
        response = urllib.request.urlopen(f"{prometheus_base_url}/api/v1/targets")
        data = json.loads(response.read())
        jobs = [t["labels"]["job"] for t in data["data"]["activeTargets"]]
        assert "api" in jobs, f"API target not found in Prometheus. Active jobs: {jobs}"

    def test_pushgateway_target_is_scraped(self, prometheus_base_url) -> None:
        """Prometheus should have the Pushgateway target configured."""
        response = urllib.request.urlopen(f"{prometheus_base_url}/api/v1/targets")
        data = json.loads(response.read())
        jobs = [t["labels"]["job"] for t in data["data"]["activeTargets"]]
        assert "pushgateway" in jobs, f"Pushgateway target not found. Active jobs: {jobs}"
