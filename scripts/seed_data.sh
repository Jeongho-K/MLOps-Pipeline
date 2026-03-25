#!/bin/bash
# Initialize MLOps Pipeline services with seed data.
# Run after `make up` when all services are healthy.

set -e

echo "=== MLOps Pipeline Seed Data ==="

# Check services are running
echo "[1/3] Checking services..."
docker compose ps --format "table {{.Name}}\t{{.Status}}" | grep -q "healthy" || {
    echo "Error: Services are not healthy. Run 'make up' first and wait for services to start."
    exit 1
}

# Create MLflow experiment
echo "[2/3] Creating MLflow experiment..."
docker compose exec mlflow mlflow experiments create --experiment-name "default-classification" 2>/dev/null || {
    echo "  MLflow experiment already exists or MLflow not ready. Skipping."
}

echo "[3/3] Verifying services..."
echo "  PostgreSQL: $(docker compose exec postgres psql -U ${POSTGRES_USER:-mlops} -c '\l' 2>/dev/null | grep -c 'mlflow\|prefect') databases found"
echo "  MinIO: $(docker compose exec minio mc ls local/ 2>/dev/null | wc -l | tr -d ' ') buckets found"
echo "  MLflow: $(curl -sf http://localhost:${MLFLOW_PORT:-5000}/health && echo 'OK' || echo 'UNREACHABLE')"
echo "  Prefect: $(curl -sf http://localhost:${PREFECT_PORT:-4200}/api/health && echo 'OK' || echo 'UNREACHABLE')"
echo "  Redis: $(docker compose exec redis redis-cli ping 2>/dev/null || echo 'UNREACHABLE')"

echo ""
echo "=== Seed complete ==="
