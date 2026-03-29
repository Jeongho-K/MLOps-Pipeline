# Serving image — FastAPI inference API with Gunicorn + Uvicorn workers
# Phase 5: Model inference serving

# --- Stage 1: Builder (install dependencies) ---
FROM python:3.11.12-slim AS builder

WORKDIR /app

# Install build dependencies
RUN pip install --no-cache-dir --upgrade pip uv

# Copy dependency definition
COPY pyproject.toml ./

# Install runtime dependencies (no dev group)
RUN uv pip install --system --no-cache-dir \
    fastapi>=0.115 \
    uvicorn[standard]>=0.30 \
    gunicorn>=22.0 \
    python-multipart>=0.0.9 \
    Pillow>=11.0 \
    torch>=2.6 \
    torchvision>=0.21 \
    mlflow>=3.10 \
    pydantic-settings>=2.7 \
    boto3>=1.35 \
    prometheus-client>=0.21 \
    prometheus-fastapi-instrumentator>=7.0

# --- Stage 2: Runtime ---
FROM python:3.11.12-slim AS runtime

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy application source
COPY src/ ./src/

EXPOSE 8000

# Use exec form for graceful shutdown support
ENTRYPOINT ["gunicorn", \
    "-c", "src/serving/gunicorn/config.py", \
    "src.serving.api.app:create_app()"]
