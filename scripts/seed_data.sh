#!/bin/bash
# Initialize MLOps Pipeline with default MLflow experiments and verify service health.
# Run after `make up` when all services are healthy.

set -eu

echo "=== MLOps Pipeline Seed Data ==="

# Check that ALL required services are healthy
echo "[1/3] Checking services..."
for svc in postgres minio mlflow prefect-server redis; do
    if ! docker compose ps "$svc" --format "{{.Status}}" 2>/dev/null | grep -q "healthy"; then
        echo "Error: $svc is not healthy. Run 'make up' first and wait for services to start."
        exit 1
    fi
    echo "  $svc: healthy"
done

# Create MLflow experiment
echo "[2/3] Creating MLflow experiment..."
OUTPUT=$(docker compose exec mlflow mlflow experiments create --experiment-name "default-classification" 2>&1) && {
    echo "  MLflow experiment 'default-classification' created."
} || {
    if echo "$OUTPUT" | grep -qi "already exists\|RESOURCE_ALREADY_EXISTS"; then
        echo "  MLflow experiment already exists. Skipping."
    else
        echo "  ERROR: Failed to create MLflow experiment:"
        echo "  $OUTPUT"
        exit 1
    fi
}

# Verify services are accessible
echo "[3/3] Verifying service accessibility..."
VERIFY_FAIL=0

curl -sf http://localhost:${MLFLOW_PORT:-5000}/health > /dev/null && echo "  MLflow: OK" || { echo "  MLflow: UNREACHABLE"; VERIFY_FAIL=1; }
curl -sf http://localhost:${PREFECT_PORT:-4200}/api/health > /dev/null && echo "  Prefect: OK" || { echo "  Prefect: UNREACHABLE"; VERIFY_FAIL=1; }
curl -sf http://localhost:${MINIO_API_PORT:-9000}/minio/health/live > /dev/null && echo "  MinIO: OK" || { echo "  MinIO: UNREACHABLE"; VERIFY_FAIL=1; }
docker compose exec redis redis-cli ping > /dev/null 2>&1 && echo "  Redis: OK" || { echo "  Redis: UNREACHABLE"; VERIFY_FAIL=1; }

if [ "$VERIFY_FAIL" -gt 0 ]; then
    echo ""
    echo "ERROR: Some services are unreachable. Run 'make verify' for details."
    exit 1
fi

echo ""
echo "=== Seed complete ==="
