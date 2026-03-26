"""Request/Response schemas for the inference API."""

from __future__ import annotations

from pydantic import BaseModel, Field


class PredictionResponse(BaseModel):
    """Classification prediction result."""

    predicted_class: int = Field(description="Predicted class index")
    class_name: str | None = Field(default=None, description="Human-readable class name if available")
    confidence: float = Field(description="Confidence score for predicted class")
    probabilities: list[float] = Field(description="Probability distribution over all classes")


class ModelInfoResponse(BaseModel):
    """Currently loaded model metadata."""

    model_name: str = Field(description="Model registry name")
    model_version: str = Field(description="Model version")
    num_classes: int = Field(description="Number of output classes")
    device: str = Field(description="Device the model is running on")
    image_size: int = Field(description="Expected input image size")


class ModelReloadRequest(BaseModel):
    """Request to reload a model from MLflow registry."""

    model_name: str | None = Field(default=None, description="Registry name (None = use current)")
    model_version: str | None = Field(default=None, description="Version (None = use current)")


class ModelReloadResponse(BaseModel):
    """Result of model reload operation."""

    status: str = Field(description="'ok' or 'error'")
    message: str = Field(description="Human-readable result description")
    model_info: ModelInfoResponse | None = Field(default=None, description="New model info if reload succeeded")


class HealthResponse(BaseModel):
    """Health check response."""

    status: str = Field(default="ok")
    model_loaded: bool = Field(description="Whether a model is currently loaded")
