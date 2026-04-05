"""Training configuration using Pydantic Settings."""

from __future__ import annotations

from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings


class TrainConfig(BaseSettings):
    """Configuration for model training.

    Values can be overridden via environment variables with TRAIN_ prefix,
    CLI arguments (see train.py), or passed directly to the constructor.
    """

    model_config = {"env_prefix": "TRAIN_"}

    # Model
    model_name: str = Field(default="resnet18", description="Model architecture name")
    num_classes: int = Field(default=10, ge=1, description="Number of output classes")
    pretrained: bool = Field(default=True, description="Use pretrained weights")

    # Training
    epochs: int = Field(default=10, ge=1, description="Number of training epochs")
    batch_size: int = Field(default=32, ge=1, description="Batch size")
    learning_rate: float = Field(default=1e-3, gt=0, description="Initial learning rate")
    weight_decay: float = Field(default=1e-4, ge=0, description="Weight decay for optimizer")
    image_size: int = Field(default=224, ge=1, description="Input image size")

    # Data
    data_dir: str = Field(default="data/raw/cifar10-demo", description="Dataset directory")
    num_workers: int = Field(default=4, ge=0, description="DataLoader workers")

    # MLflow
    experiment_name: str = Field(default="default-classification", description="MLflow experiment name")
    mlflow_tracking_uri: str = Field(default="http://localhost:5000", description="MLflow server URI")
    registered_model_name: str | None = Field(default=None, description="Model registry name (None = skip)")

    # Device
    device: Literal["auto", "cpu", "cuda", "mps"] = Field(default="auto", description="Device")
