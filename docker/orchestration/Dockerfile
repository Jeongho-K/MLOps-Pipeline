# Prefect worker image that registers all four core deployments
# (continuous training, active learning, monitoring, data accumulation)
# on startup via src.core.orchestration.flows.serve_all, and then serves
# them from a single runner process. Uses the same prefect base as the
# prefect-server service to guarantee protocol compatibility.

FROM prefecthq/prefect:3.6.23-python3.11

WORKDIR /app

# Install uv for fast dependency resolution, then add the runtime libs.
# torch/torchvision power the training flow; pandas/evidently/scikit-learn
# power the monitoring flow's drift detection.
RUN pip install --no-cache-dir --upgrade pip uv \
    && uv pip install --system --no-cache-dir \
        mlflow>=3.10 \
        torch>=2.6 \
        torchvision>=0.21 \
        boto3>=1.35 \
        pydantic-settings>=2.7 \
        Pillow>=11.0 \
        prometheus-client>=0.21 \
        httpx>=0.27 \
        numpy>=1.26 \
        pandas>=2.2 \
        evidently>=0.5 \
        scikit-learn>=1.4 \
        cleanlab>=2.7 \
        cleanvision>=0.3.6

# Application source so ``python -m src.core.orchestration.flows...``
# resolves against an installed-style module layout.
COPY src/ ./src/

# ``prefect.serve(...)`` is blocking — it registers every RunnerDeployment
# on the Prefect server and then polls for triggers. The container runs as
# a long-lived service, restarted by compose on failure.
ENTRYPOINT ["python", "-m", "src.core.orchestration.flows.serve_all"]
