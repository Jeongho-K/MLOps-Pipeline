"""Continuous Training configuration using Pydantic Settings.

Phase B configuration for event-driven retraining, quality gates,
and champion model management.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings


class ContinuousTrainingConfig(BaseSettings):
    """Configuration for the continuous training loop.

    Values can be overridden via environment variables with CT_ prefix
    or passed directly to the constructor.
    """

    model_config = {"env_prefix": "CT_"}

    # Data integration
    merged_data_dir: str = Field(
        default="data/merged",
        description="Directory for merged training data (ImageFolder format)",
    )
    train_val_split: float = Field(
        default=0.8,
        gt=0.0,
        lt=1.0,
        description="Fraction of data used for training (rest for validation)",
    )

    # Retrain trigger thresholds
    min_annotation_count: int = Field(
        default=50,
        ge=1,
        description="Minimum completed annotations to trigger retraining",
    )
    min_accumulated_samples: int = Field(
        default=100,
        ge=1,
        description="Minimum pseudo-label samples to trigger retraining",
    )

    # G2: Training quality gate
    min_val_accuracy: float = Field(
        default=0.7,
        ge=0.0,
        le=1.0,
        description="Minimum validation accuracy to pass G2 gate",
    )
    max_overfit_gap: float = Field(
        default=0.15,
        ge=0.0,
        description="Maximum allowed gap between val_loss and train_loss (overfitting check)",
    )

    # G3: Champion gate
    champion_metric: str = Field(
        default="best_val_accuracy",
        description="Metric to compare challenger vs champion model",
    )
    champion_margin: float = Field(
        default=0.0,
        ge=0.0,
        description="Challenger must exceed champion by this margin to pass G3",
    )

    # Round tracking
    round_state_bucket: str = Field(
        default="active-learning",
        description="S3 bucket for round state file",
    )
    round_state_key: str = Field(
        default="rounds/round_state.json",
        description="S3 key for round state JSON file",
    )

    # Prefect deployment
    deployment_name: str = Field(
        default="continuous-training/continuous-training-deployment",
        description="Prefect deployment name for run_deployment() calls",
    )

    # S3 connection (reuses AL_ defaults where possible)
    s3_endpoint: str = Field(
        default="http://minio:9000",
        description="S3-compatible endpoint URL",
    )
    s3_access_key: str = Field(
        default="",
        description="AWS/MinIO access key ID",
    )
    s3_secret_key: str = Field(
        default="",
        description="AWS/MinIO secret access key",
    )

    # MLflow
    mlflow_tracking_uri: str = Field(
        default="http://localhost:5000",
        description="MLflow tracking server URI",
    )
    registered_model_name: str = Field(
        default="cv-classifier",
        description="MLflow registered model name for champion/challenger tracking",
    )

    # Label Studio
    label_studio_url: str = Field(
        default="http://label-studio:8080",
        description="Label Studio API URL",
    )
    label_studio_api_key: str = Field(
        default="",
        description="Label Studio API key",
    )
    label_studio_project_id: int = Field(
        default=1,
        ge=1,
        description="Label Studio project ID for annotation export",
    )
