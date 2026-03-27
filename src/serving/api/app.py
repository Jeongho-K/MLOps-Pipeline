"""FastAPI application with lifespan-managed model loading."""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from fastapi import FastAPI

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

from src.monitoring.metrics import setup_metrics
from src.monitoring.prediction_logger import PredictionLogger
from src.serving.api.config import ServingConfig
from src.serving.api.dependencies import (
    ModelState,
    load_model_from_registry,
    resolve_device,
)
from src.serving.api.routes import router

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Manage application lifecycle: load model on startup, cleanup on shutdown."""
    config: ServingConfig = app.state.serving_config

    device = resolve_device(config.device)
    logger.info("Inference device: %s", device)

    try:
        model_state = load_model_from_registry(
            model_name=config.model_name,
            model_version=config.model_version,
            mlflow_tracking_uri=config.mlflow_tracking_uri,
            device=device,
            image_size=config.image_size,
        )
    except RuntimeError:
        logger.exception(
            "Failed to load model on startup. Server will start without a model. "
            "Use POST /model/reload to load a model later."
        )
        model_state = ModelState(device=device, image_size=config.image_size)

    app.state.model_state = model_state

    s3_endpoint = os.getenv("MLFLOW_S3_ENDPOINT_URL", "http://minio:9000")
    app.state.prediction_logger = PredictionLogger(
        s3_endpoint=s3_endpoint,
        bucket="prediction-logs",
        access_key=os.getenv("AWS_ACCESS_KEY_ID", "minioadmin"),
        secret_key=os.getenv("AWS_SECRET_ACCESS_KEY", "minioadmin123"),
    )

    yield

    logger.info("Shutting down, releasing model resources")
    if hasattr(app.state, "prediction_logger"):
        app.state.prediction_logger.flush()
    app.state.model_state = ModelState()


def create_app(config: ServingConfig | None = None, *, enable_lifespan: bool = True) -> FastAPI:
    """Create and configure the FastAPI application.

    Args:
        config: Serving configuration. Defaults to loading from environment.
        enable_lifespan: Whether to enable lifespan events (model loading on startup).
            Set to False for testing without MLflow connectivity.

    Returns:
        Configured FastAPI application.
    """
    if config is None:
        config = ServingConfig()

    app = FastAPI(
        title="MLOps Pipeline - Inference API",
        description="Image classification inference API with MLflow model registry integration.",
        version="0.1.0",
        lifespan=lifespan if enable_lifespan else None,
    )

    # Store config on app state so routes can access it
    app.state.serving_config = config
    # Initialize empty model state (lifespan will populate it)
    app.state.model_state = ModelState()

    app.include_router(router)
    setup_metrics(app)

    return app
