"""CLI entrypoint for training.

Usage:
    uv run python -m src.plugins.cv.train
    uv run python -m src.plugins.cv.train --model-name resnet50 --epochs 20
"""

from __future__ import annotations

import argparse
import logging
import sys

from src.plugins.cv.configs.train_config import TrainConfig
from src.plugins.cv.trainer import train

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def main() -> None:
    """Parse arguments and run training."""
    parser = argparse.ArgumentParser(description="Train image classification model")
    parser.add_argument("--model-name", type=str, help="Model architecture")
    parser.add_argument("--num-classes", type=int, help="Number of classes")
    parser.add_argument("--epochs", type=int, help="Number of epochs")
    parser.add_argument("--batch-size", type=int, help="Batch size")
    parser.add_argument("--learning-rate", type=float, help="Learning rate")
    parser.add_argument("--data-dir", type=str, help="Dataset directory")
    parser.add_argument("--experiment-name", type=str, help="MLflow experiment name")
    parser.add_argument("--mlflow-tracking-uri", type=str, help="MLflow server URI")
    parser.add_argument("--registered-model-name", type=str, help="Model registry name")
    parser.add_argument("--device", type=str, help="Device: auto, cpu, cuda, mps")

    args = parser.parse_args()

    # Build config from env vars, then override with CLI args
    overrides = {k: v for k, v in vars(args).items() if v is not None}
    config = TrainConfig(**overrides)

    logger.info("Training config: %s", config.model_dump())

    try:
        metrics = train(config)
        logger.info("Training complete: %s", metrics)
    except FileNotFoundError as e:
        logger.error("Data not found: %s", e)
        sys.exit(1)
    except ConnectionError as e:
        logger.error("MLflow connection failed: %s. Is the server running at %s?", e, config.mlflow_tracking_uri)
        sys.exit(1)
    except Exception:
        logger.exception("Training failed with unexpected error")
        sys.exit(1)


if __name__ == "__main__":
    main()
