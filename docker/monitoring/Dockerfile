# Monitoring image - Evidently drift detection worker
# Phase 6: Data and model monitoring

FROM python:3.11.12-slim AS base

WORKDIR /app

# --- Dependencies ---
FROM base AS deps
COPY pyproject.toml uv.lock ./
RUN pip install --no-cache-dir uv && \
    uv sync --frozen --no-dev --no-install-project

# --- Source ---
FROM base AS runtime
COPY --from=deps /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"

COPY src/ ./src/

ENTRYPOINT ["python3", "-m", "src.core.orchestration.flows.monitoring_flow"]
