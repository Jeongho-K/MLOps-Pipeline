"""Deployment configuration using Pydantic Settings.

Phase C configuration for canary deployment, G4 canary gate,
and infrastructure management.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings


class DeploymentConfig(BaseSettings):
    """Configuration for canary deployment and G4 gate.

    Values can be overridden via environment variables with DEPLOY_ prefix
    or passed directly to the constructor.
    """

    model_config = {"env_prefix": "DEPLOY_"}

    # Canary deployment
    canary_duration_minutes: int = Field(
        default=30,
        ge=1,
        description="Total duration of canary monitoring phase in minutes",
    )
    canary_check_interval_seconds: int = Field(
        default=120,
        ge=10,
        description="Seconds between G4 canary gate checks",
    )
    canary_weight: int = Field(
        default=1,
        ge=1,
        le=10,
        description="Nginx upstream weight for canary container",
    )
    champion_weight: int = Field(
        default=9,
        ge=1,
        le=10,
        description="Nginx upstream weight for champion container",
    )

    # G4: Canary gate thresholds
    max_error_rate_ratio: float = Field(
        default=1.5,
        gt=0.0,
        description="Max canary/champion error rate ratio before rollback",
    )
    max_latency_ratio: float = Field(
        default=1.3,
        gt=0.0,
        description="Max canary/champion P99 latency ratio before rollback",
    )
    absolute_max_error_rate: float = Field(
        default=0.05,
        ge=0.0,
        le=1.0,
        description="Hard ceiling for canary error rate (absolute, not relative)",
    )

    # Infrastructure
    prometheus_url: str = Field(
        default="http://prometheus:9090",
        description="Prometheus server URL for querying metrics",
    )
    docker_compose_project: str = Field(
        default="data-flywheel",
        description="Docker Compose project name for container management",
    )
    nginx_container_name: str = Field(
        default="nginx",
        description="Name of the Nginx container for config reload",
    )
    nginx_upstream_path: str = Field(
        default="/etc/nginx/conf.d/upstream.conf",
        description="Path to Nginx upstream config inside the container",
    )
    canary_health_url: str = Field(
        default="http://api-canary:8000/health",
        description="URL to check canary container health",
    )
    champion_reload_url: str = Field(
        default="http://api:8000/model/reload",
        description="URL to trigger model reload on champion container",
    )

    # MLflow
    registered_model_name: str = Field(
        default="cv-classifier",
        description="MLflow registered model name",
    )
    mlflow_tracking_uri: str = Field(
        default="http://mlflow:5000",
        description="MLflow tracking server URI",
    )
