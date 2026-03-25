# Serving image - FastAPI with Gunicorn/Uvicorn
# Phase 5: Model inference API

# --- Stage 1: Base ---
FROM python:3.11-slim AS base

WORKDIR /app

# --- Stage 2: Dependencies ---
FROM base AS deps
# COPY requirements-serving.txt .
# RUN pip install --no-cache-dir -r requirements-serving.txt

# --- Stage 3: Runtime ---
FROM deps AS runtime
# COPY src/serving/ ./src/serving/
# EXPOSE 8000
# ENTRYPOINT ["gunicorn", "src.serving.api.main:app", "-k", "uvicorn.workers.UvicornWorker"]
