"""Serve the continuous training flow as a Prefect deployment.

Usage:
    # Serve (event-driven, no schedule — triggered by run_deployment):
    uv run python -m src.core.orchestration.flows.continuous_training_serve

    # Run once for testing:
    uv run python -m src.core.orchestration.flows.continuous_training_serve --run-once
"""

from __future__ import annotations

import argparse
import logging
import os

from src.core.orchestration.config import ContinuousTrainingConfig
from src.core.orchestration.flows.continuous_training_flow import continuous_training_flow

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def main() -> None:
    """Parse arguments and serve or run the continuous training flow."""
    parser = argparse.ArgumentParser(description="Serve continuous training deployment")
    parser.add_argument("--run-once", action="store_true", help="Run the flow once immediately")
    parser.add_argument(
        "--trigger-source",
        type=str,
        default="manual",
        help="Trigger source for --run-once (default: manual)",
    )
    args = parser.parse_args()

    # Set Prefect API URL
    prefect_api_url = os.environ.get("PREFECT_API_URL")
    if prefect_api_url is None:
        prefect_api_url = "http://localhost:4200/api"
        logger.warning(
            "PREFECT_API_URL not set, defaulting to %s.",
            prefect_api_url,
        )
    os.environ["PREFECT_API_URL"] = prefect_api_url
    logger.info("Using Prefect API at %s", prefect_api_url)

    config = ContinuousTrainingConfig()

    params = {
        "trigger_source": args.trigger_source,
        "s3_endpoint": config.s3_endpoint,
        "s3_access_key": config.s3_access_key,
        "s3_secret_key": config.s3_secret_key,
        "merged_data_dir": config.merged_data_dir,
        "train_val_split": config.train_val_split,
        "label_studio_url": config.label_studio_url,
        "label_studio_api_key": config.label_studio_api_key,
        "label_studio_project_id": config.label_studio_project_id,
        "mlflow_tracking_uri": config.mlflow_tracking_uri,
        "registered_model_name": config.registered_model_name,
        "min_val_accuracy": config.min_val_accuracy,
        "max_overfit_gap": config.max_overfit_gap,
        "champion_metric": config.champion_metric,
        "champion_margin": config.champion_margin,
        "round_state_bucket": config.round_state_bucket,
        "round_state_key": config.round_state_key,
    }

    if args.run_once:
        logger.info("Running continuous training flow once with trigger=%s", args.trigger_source)
        try:
            result = continuous_training_flow(**params)
            logger.info("Flow complete: %s", result)
        except Exception:
            logger.exception("Continuous training flow failed")
            raise SystemExit(1) from None
    else:
        logger.info("Serving continuous training deployment (event-driven, no schedule)")
        try:
            continuous_training_flow.serve(
                name="continuous-training-deployment",
                parameters=params,
                tags=["continuous-training", "phase-b"],
            )
        except KeyboardInterrupt:
            logger.info("Deployment serve interrupted by user. Shutting down.")
        except Exception:
            logger.exception(
                "Failed to serve continuous training flow. Check PREFECT_API_URL (%s).",
                os.environ.get("PREFECT_API_URL", "not set"),
            )
            raise SystemExit(1) from None


if __name__ == "__main__":
    main()
