"""Request/Response schemas for the inference API."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class PredictionResponse(BaseModel):
    """Classification prediction result."""

    predicted_class: int = Field(ge=0, description="Predicted class index")
    class_name: str | None = Field(default=None, description="Human-readable class name if available")
    confidence: float = Field(ge=0.0, le=1.0, description="Confidence score for predicted class")
    probabilities: list[float] = Field(min_length=1, description="Probability distribution over all classes")
    uncertainty_score: float | None = Field(
        default=None, ge=0.0, le=1.0, description="Uncertainty score (0=certain, 1=uncertain)"
    )
    routing_decision: str | None = Field(
        default=None, description="AL routing: auto_accumulate, human_review, or discard"
    )


class ModelInfoResponse(BaseModel):
    """Currently loaded model metadata."""

    model_name: str = Field(description="Model registry name")
    model_version: str = Field(description="Model version")
    mlflow_run_id: str = Field(default="", description="MLflow training run ID")
    num_classes: int = Field(description="Number of output classes")
    device: str = Field(description="Device the model is running on")
    image_size: int = Field(description="Expected input image size")


class ModelReloadRequest(BaseModel):
    """Request to reload a model from MLflow registry."""

    model_name: str | None = Field(default=None, description="Registry name (None = use current)")
    model_version: str | None = Field(default=None, description="Version (None = use current)")


class ModelReloadResponse(BaseModel):
    """Result of model reload operation."""

    status: Literal["ok"] = Field(description="Always 'ok' for successful reload")
    message: str = Field(description="Human-readable result description")
    model_info: ModelInfoResponse | None = Field(default=None, description="New model info if reload succeeded")


class HealthResponse(BaseModel):
    """Health check response."""

    status: Literal["ok"] = Field(default="ok")
    model_loaded: bool = Field(description="Whether a model is currently loaded")
