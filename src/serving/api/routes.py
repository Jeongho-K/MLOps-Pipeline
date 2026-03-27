"""API route definitions for the inference server."""

from __future__ import annotations

import io
import logging

import torch
from fastapi import APIRouter, HTTPException, Request, UploadFile
from PIL import Image

from src.data.preprocessing.transforms import get_eval_transforms
from src.monitoring.metrics import record_prediction
from src.serving.api.dependencies import ModelState, load_model_from_registry
from src.serving.api.schemas import (
    HealthResponse,
    ModelInfoResponse,
    ModelReloadRequest,
    ModelReloadResponse,
    PredictionResponse,
)

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
        )

    return PredictionResponse(
        predicted_class=predicted_idx,
        class_name=class_name,
        confidence=confidence,
        probabilities=probs,
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

    return ModelReloadResponse(
        status="ok",
        message=f"Reloaded model '{target_name}' version '{target_version}'",
        model_info=ModelInfoResponse(**new_state.to_info_dict()),
    )
