"""FastAPI application with lifespan-managed model loading."""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

from fastapi import FastAPI

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

from src.common.device import resolve_device
from src.core.active_learning.accumulator.auto_accumulator import AutoAccumulator
from src.core.active_learning.config import ActiveLearningConfig
from src.core.active_learning.labeling.webhook import webhook_router
from src.core.active_learning.routing.confidence_router import ConfidenceRouter
from src.core.monitoring.metrics import setup_metrics
from src.core.monitoring.prediction_logger import PredictionLogger
from src.core.serving.api.admin import admin_router
from src.core.serving.api.config import ServingConfig
from src.core.serving.api.dependencies import (
    ModelState,
    load_model_from_registry,
)
from src.core.serving.api.routes import router
from src.core.serving.reload_sync import ReloadSubscriber
from src.plugins.cv.uncertainty import SoftmaxEntropyEstimator

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

    app.state.prediction_logger = PredictionLogger(
        s3_endpoint=config.s3_endpoint,
        bucket=config.prediction_logs_bucket,
        access_key=os.environ["AWS_ACCESS_KEY_ID"],
        secret_key=os.environ["AWS_SECRET_ACCESS_KEY"],
    )

    # Active Learning components
    al_config = ActiveLearningConfig()
    app.state.uncertainty_estimator = SoftmaxEntropyEstimator()
    app.state.confidence_router = ConfidenceRouter(
        auto_threshold=al_config.auto_accumulate_threshold,
        uncertainty_threshold=al_config.uncertainty_threshold,
    )
    app.state.auto_accumulator = AutoAccumulator(
        s3_endpoint=al_config.s3_endpoint,
        bucket=al_config.accumulation_bucket,
        prefix=al_config.accumulation_prefix,
        access_key=os.environ["AWS_ACCESS_KEY_ID"],
        secret_key=os.environ["AWS_SECRET_ACCESS_KEY"],
        flush_threshold=al_config.accumulation_buffer_size,
    )
    logger.info(
        "Active Learning enabled: auto_threshold=%.2f, uncertainty_threshold=%.2f",
        al_config.auto_accumulate_threshold,
        al_config.uncertainty_threshold,
    )

    # Register Label Studio webhook (best-effort: don't block startup)
    if al_config.label_studio_api_key:
        try:
            from src.core.active_learning.labeling.bridge import LabelStudioBridge

            bridge = LabelStudioBridge(
                base_url=al_config.label_studio_url,
                api_key=al_config.label_studio_api_key,
                project_id=al_config.label_studio_project_id,
            )
            try:
                bridge.register_webhook(al_config.webhook_callback_url)
            finally:
                bridge.close()
        except Exception:
            logger.warning("Failed to register Label Studio webhook on startup", exc_info=True)
    else:
        logger.info("Label Studio API key not set — skipping webhook registration")

    # Start Redis Pub/Sub subscriber for cross-worker model reload sync
    redis_url = os.environ.get("REDIS_URL", "redis://redis:6379/0")

    def _handle_remote_reload(payload: dict[str, Any]) -> None:
        """Reload model when notified by another worker."""
        target_name = payload.get("model_name", config.model_name)
        target_version = payload.get("model_version", config.model_version)
        logger.info("Remote reload triggered: %s version %s", target_name, target_version)
        try:
            new_state = load_model_from_registry(
                model_name=target_name,
                model_version=target_version,
                mlflow_tracking_uri=config.mlflow_tracking_uri,
                device=device,
                image_size=config.image_size,
            )
            app.state.model_state = new_state
            logger.info("Remote reload complete: %s version %s", target_name, target_version)
        except Exception:
            logger.exception("Remote reload failed for %s version %s", target_name, target_version)

    reload_subscriber = ReloadSubscriber(redis_url=redis_url, on_reload=_handle_remote_reload)
    reload_subscriber.start()
    app.state.reload_subscriber = reload_subscriber

    yield

    logger.info("Shutting down, releasing model resources")
    reload_subscriber.stop()
    app.state.prediction_logger.flush()
    app.state.auto_accumulator.flush()
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
        title="Data Flywheel - Inference API",
        description="Image classification inference API with MLflow model registry integration.",
        version="0.1.0",
        lifespan=lifespan if enable_lifespan else None,
    )

    # Store config on app state so routes can access it
    app.state.serving_config = config
    # Initialize empty model state (lifespan will populate it)
    app.state.model_state = ModelState()

    app.include_router(router)
    app.include_router(webhook_router)
    app.include_router(admin_router)
    setup_metrics(app)

    return app
