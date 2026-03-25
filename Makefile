.PHONY: up down down-v ps logs seed lint format test verify install

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
