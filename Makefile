.PHONY: up down down-v ps logs seed lint format test verify install train pipeline pipeline-serve drift-check canary-up canary-down canary-status

# ---------------------------------------------------------------------------
# Docker Compose
# ---------------------------------------------------------------------------
up:
	docker compose up -d

down:
	docker compose down

down-v:
	docker compose down -v

ps:
	docker compose ps

logs:
ifndef SERVICE
	$(error Usage: make logs SERVICE=<name>)
endif
	docker compose logs -f $(SERVICE)

# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------
seed:
	@test -f scripts/seed_data.sh || { echo "Error: scripts/seed_data.sh not found. Available after Phase 1."; exit 1; }
	bash scripts/seed_data.sh

verify:
	@test -f scripts/verify.sh || { echo "Error: scripts/verify.sh not found. Available after Phase 1."; exit 1; }
	bash scripts/verify.sh

# ---------------------------------------------------------------------------
# Dependencies (uv)
# ---------------------------------------------------------------------------
install:
	uv sync

# ---------------------------------------------------------------------------
# Training
# ---------------------------------------------------------------------------
train:
	uv run python -m src.training.train

pipeline:
	uv run python -m src.orchestration.serve --run-once

pipeline-serve:
	uv run python -m src.orchestration.serve

# ---------------------------------------------------------------------------
# Monitoring
# ---------------------------------------------------------------------------
drift-check:
	DRIFT_S3_ENDPOINT=http://localhost:9000 DRIFT_S3_ACCESS_KEY=$(MINIO_ROOT_USER) DRIFT_S3_SECRET_KEY=$(MINIO_ROOT_PASSWORD) DRIFT_PUSHGATEWAY_URL=http://localhost:9091 \
	uv run python -c "from src.orchestration.flows.monitoring_flow import monitoring_pipeline; monitoring_pipeline(s3_endpoint='http://localhost:9000', pushgateway_url='http://localhost:9091')"

# ---------------------------------------------------------------------------
# Code Quality
# ---------------------------------------------------------------------------
lint:
	uv run ruff check src/ tests/

format:
	uv run ruff format src/ tests/

# ---------------------------------------------------------------------------
# Testing
# ---------------------------------------------------------------------------
test:
	uv run pytest tests/unit/ -v

test-integration:
	uv run pytest tests/integration/ -v

test-e2e:
	uv run pytest tests/e2e/ -v

# ---------------------------------------------------------------------------
# Canary Deployment (Phase C)
# ---------------------------------------------------------------------------
canary-up:
	docker compose --profile canary up -d api-canary

canary-down:
	docker compose --profile canary stop api-canary

canary-status:
	@docker compose --profile canary ps api-canary 2>/dev/null || echo "Canary not running"
