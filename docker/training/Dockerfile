# Training image - GPU-enabled multi-stage build
# Phase 3: PyTorch training with MLflow integration

# --- Stage 1: Base ---
FROM nvidia/cuda:12.6.3-runtime-ubuntu22.04 AS base

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3.11 \
    python3.11-venv \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# --- Stage 2: Dependencies ---
FROM base AS deps
# COPY requirements.txt .
# RUN pip install --no-cache-dir -r requirements.txt

# --- Stage 3: Runtime ---
FROM deps AS runtime
# COPY src/ ./src/
# ENTRYPOINT ["python3", "-m", "src.training"]
