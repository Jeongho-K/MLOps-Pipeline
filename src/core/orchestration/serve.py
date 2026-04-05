"""Serve Prefect flows as deployments.

Usage:
    # Run once (no schedule):
    uv run python -m src.core.orchestration.serve --run-once

    # Serve with weekly schedule:
    uv run python -m src.core.orchestration.serve

    # Serve with daily schedule:
    uv run python -m src.core.orchestration.serve --cron "0 2 * * *"

Note: Not all pipeline parameters are exposed via CLI. Use environment
variables (TRAIN_ prefix) to configure additional training settings.
"""

from __future__ import annotations

import argparse
import logging
import os

from src.core.orchestration.flows.training_pipeline import training_pipeline

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
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--learning-rate", type=float, default=1e-3)
    parser.add_argument("--experiment-name", type=str, default="default-classification")
    parser.add_argument("--registered-model-name", type=str, default=None)
    parser.add_argument("--min-health-score", type=float, default=0.5)
    parser.add_argument("--mlflow-tracking-uri", type=str, default="http://localhost:5000")

    args = parser.parse_args()

    # Set Prefect API URL for connecting to the server
    prefect_api_url = os.environ.get("PREFECT_API_URL")
    if prefect_api_url is None:
        prefect_api_url = "http://localhost:4200/api"
        logger.warning(
            "PREFECT_API_URL not set, defaulting to %s. Set this environment variable for production deployments.",
            prefect_api_url,
        )
    os.environ["PREFECT_API_URL"] = prefect_api_url
    logger.info("Using Prefect API at %s", prefect_api_url)

    params = {
        "data_dir": args.data_dir,
        "model_name": args.model_name,
        "num_classes": args.num_classes,
        "epochs": args.epochs,
        "batch_size": args.batch_size,
        "learning_rate": args.learning_rate,
        "experiment_name": args.experiment_name,
        "registered_model_name": args.registered_model_name,
        "min_health_score": args.min_health_score,
        "mlflow_tracking_uri": args.mlflow_tracking_uri,
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
        try:
            training_pipeline.serve(
                name="training-pipeline-deployment",
                cron=args.cron,
                parameters=params,
                tags=["training", "cv"],
            )
        except KeyboardInterrupt:
            logger.info("Deployment serve interrupted by user. Shutting down.")
        except Exception:
            logger.exception(
                "Failed to serve training pipeline. Check PREFECT_API_URL (%s) and cron expression '%s'.",
                os.environ.get("PREFECT_API_URL", "not set"),
                args.cron,
            )
            raise SystemExit(1) from None


if __name__ == "__main__":
    main()
