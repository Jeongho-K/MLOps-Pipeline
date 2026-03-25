"""Serve Prefect flows as deployments.

Usage:
    # Run once (no schedule):
    uv run python -m src.orchestration.serve --run-once

    # Serve with weekly schedule:
    uv run python -m src.orchestration.serve

    # Serve with daily schedule:
    uv run python -m src.orchestration.serve --cron "0 2 * * *"
"""

from __future__ import annotations

import argparse
import logging
import os

from src.orchestration.flows.training_pipeline import training_pipeline

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def main() -> None:
    """Parse arguments and serve or run the training pipeline."""
    parser = argparse.ArgumentParser(description="Serve training pipeline deployment")
    parser.add_argument("--run-once", action="store_true", help="Run the pipeline once immediately")
    parser.add_argument("--cron", type=str, default="0 2 * * 1", help="Cron schedule (default: weekly Monday 2AM)")
    parser.add_argument("--data-dir", type=str, default="data/raw/cifar10-demo")
    parser.add_argument("--model-name", type=str, default="resnet18")
    parser.add_argument("--num-classes", type=int, default=10)
    parser.add_argument("--epochs", type=int, default=10)
    parser.add_argument("--experiment-name", type=str, default="default-classification")
    parser.add_argument("--registered-model-name", type=str, default=None)

    args = parser.parse_args()

    # Set Prefect API URL for connecting to the server
    os.environ.setdefault("PREFECT_API_URL", "http://localhost:4200/api")

    params = {
        "data_dir": args.data_dir,
        "model_name": args.model_name,
        "num_classes": args.num_classes,
        "epochs": args.epochs,
        "experiment_name": args.experiment_name,
        "registered_model_name": args.registered_model_name,
    }

    if args.run_once:
        logger.info("Running training pipeline once with params: %s", params)
        try:
            metrics = training_pipeline(**params)
            logger.info("Pipeline complete: %s", metrics)
        except Exception:
            logger.exception("Pipeline failed")
            raise SystemExit(1) from None
    else:
        logger.info("Serving training pipeline with cron='%s'", args.cron)
        training_pipeline.serve(
            name="training-pipeline-deployment",
            cron=args.cron,
            parameters=params,
            tags=["training", "cv"],
        )


if __name__ == "__main__":
    main()
