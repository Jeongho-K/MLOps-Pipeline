"""API route definitions for the inference server."""

from __future__ import annotations

import io
import logging
from datetime import UTC, datetime

import torch
from fastapi import APIRouter, HTTPException, Request, UploadFile
from PIL import Image

from src.core.active_learning.accumulator.models import AccumulatedSample
from src.core.monitoring.metrics import record_prediction, record_routing
from src.core.serving.api.dependencies import ModelState, load_model_from_registry
from src.core.serving.api.schemas import (
    HealthResponse,
    ModelInfoResponse,
    ModelReloadRequest,
    ModelReloadResponse,
    PredictionResponse,
)
from src.plugins.cv.transforms import get_eval_transforms

logger = logging.getLogger(__name__)

router = APIRouter()


def _get_model_state(request: Request) -> ModelState:
    """Retrieve model state from app, raising 503 if not loaded."""
    model_state: ModelState = request.app.state.model_state
    if not model_state.is_loaded:
        raise HTTPException(status_code=503, detail="Model not loaded")
    return model_state


@router.get("/health", response_model=HealthResponse)
async def health(request: Request) -> HealthResponse:
    """Health check endpoint."""
    model_state: ModelState = request.app.state.model_state
    return HealthResponse(model_loaded=model_state.is_loaded)


@router.get("/model/info", response_model=ModelInfoResponse)
async def model_info(request: Request) -> ModelInfoResponse:
    """Return metadata about the currently loaded model."""
    ms = _get_model_state(request)
    return ModelInfoResponse(**ms.to_info_dict())


@router.post("/predict", response_model=PredictionResponse)
async def predict(request: Request, file: UploadFile) -> PredictionResponse:
    """Run inference on an uploaded image.

    Args:
        request: FastAPI request (carries app state).
        file: Uploaded image file (JPEG, PNG, etc.).

    Returns:
        Classification prediction with confidence scores.
    """
    ms = _get_model_state(request)

    # Read and validate image
    contents = await file.read()

    # File size check (10 MB limit)
    max_image_size = 10 * 1024 * 1024
    if len(contents) > max_image_size:
        raise HTTPException(status_code=413, detail="Image exceeds 10 MB size limit")
    if len(contents) < 8:
        raise HTTPException(status_code=400, detail="Uploaded file is too small to be a valid image")

    # Magic bytes validation (JPEG, PNG, GIF, BMP, WebP, TIFF)
    image_magic = (
        b"\xff\xd8\xff",        # JPEG
        b"\x89PNG\r\n\x1a\n",   # PNG
        b"GIF87a", b"GIF89a",   # GIF
        b"BM",                   # BMP
        b"RIFF",                 # WebP (starts with RIFF)
        b"II\x2a\x00", b"MM\x00\x2a",  # TIFF
    )
    if not contents[:8].startswith(image_magic):
        raise HTTPException(status_code=400, detail="Unsupported image format")

    try:
        image = Image.open(io.BytesIO(contents)).convert("RGB")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid image file: {exc}") from exc

    # Preprocess + Inference
    try:
        transform = get_eval_transforms(ms.image_size)
        input_tensor: torch.Tensor = transform(image).unsqueeze(0).to(ms.device)

        with torch.no_grad():
            output = ms.model(input_tensor)
            probabilities = torch.nn.functional.softmax(output, dim=1)

        probs = probabilities.squeeze(0).cpu().tolist()
        predicted_idx = int(torch.argmax(probabilities, dim=1).item())
        confidence = probs[predicted_idx]
    except Exception as exc:
        logger.exception("Inference failed for uploaded image")
        raise HTTPException(status_code=500, detail=f"Inference error: {exc}") from exc

    class_names = request.app.state.serving_config.get_class_names_list()
    class_name = class_names[predicted_idx] if class_names and predicted_idx < len(class_names) else None

    # Active Learning: uncertainty estimation and confidence routing
    uncertainty_score: float | None = None
    routing_decision: str | None = None

    uncertainty_estimator = getattr(request.app.state, "uncertainty_estimator", None)
    confidence_router = getattr(request.app.state, "confidence_router", None)

    if uncertainty_estimator is not None:
        uncertainty_scores = uncertainty_estimator.estimate([probs])
        uncertainty_score = uncertainty_scores[0]

    if confidence_router is not None and uncertainty_score is not None:
        decision = confidence_router.route(confidence, uncertainty_score)
        routing_decision = decision.route

        if decision.route == "auto_accumulate":
            accumulator = getattr(request.app.state, "auto_accumulator", None)
            if accumulator is not None:
                accumulator.add(
                    AccumulatedSample(
                        timestamp=datetime.now(tz=UTC).isoformat(),
                        predicted_class=predicted_idx,
                        class_name=class_name,
                        confidence=confidence,
                        probabilities=probs,
                        model_version=ms.model_version,
                        image_bytes=contents,
                    )
                )

        record_routing(
            routing_decision=decision.route,
            uncertainty_score=uncertainty_score,
            accumulation_buffer_size=getattr(getattr(request.app.state, "auto_accumulator", None), "buffer_size", None),
        )

    # Record metrics and log prediction
    record_prediction(
        predicted_class=predicted_idx,
        confidence=confidence,
        class_name=class_name,
    )

    prediction_logger = getattr(request.app.state, "prediction_logger", None)
    if prediction_logger is not None:
        prediction_logger.log(
            predicted_class=predicted_idx,
            confidence=confidence,
            probabilities=probs,
            class_name=class_name,
            model_version=ms.model_version,
            mlflow_run_id=ms.mlflow_run_id,
            uncertainty_score=uncertainty_score,
            routing_decision=routing_decision,
        )

    return PredictionResponse(
        predicted_class=predicted_idx,
        class_name=class_name,
        confidence=confidence,
        probabilities=probs,
        uncertainty_score=uncertainty_score,
        routing_decision=routing_decision,
    )


@router.post("/model/reload", response_model=ModelReloadResponse)
async def model_reload(request: Request, body: ModelReloadRequest) -> ModelReloadResponse:
    """Reload the model from MLflow registry.

    Allows switching to a different model version without restarting the server.
    """
    config = request.app.state.serving_config
    current_state: ModelState = request.app.state.model_state

    target_name = body.model_name or current_state.model_name or config.model_name
    target_version = body.model_version or current_state.model_version or config.model_version

    try:
        new_state = load_model_from_registry(
            model_name=target_name,
            model_version=target_version,
            mlflow_tracking_uri=config.mlflow_tracking_uri,
            device=current_state.device,
            image_size=config.image_size,
        )
    except Exception as exc:
        logger.exception("Model reload failed for '%s' version '%s'", target_name, target_version)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to load model '{target_name}' version '{target_version}'",
        ) from exc

    request.app.state.model_state = new_state

    # Notify other Gunicorn workers via Redis Pub/Sub
    reload_subscriber = getattr(request.app.state, "reload_subscriber", None)
    if reload_subscriber is not None and reload_subscriber.is_active:
        reload_subscriber.publish_reload({"model_name": target_name, "model_version": target_version})

    return ModelReloadResponse(
        status="ok",
        message=f"Reloaded model '{target_name}' version '{target_version}'",
        model_info=ModelInfoResponse(**new_state.to_info_dict()),
    )
