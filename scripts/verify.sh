#!/bin/bash
# Verify MLOps Pipeline infrastructure is working correctly.
# Run after `make up` when all services are healthy.

set -eu

PASS=0
FAIL=0

check() {
    local name="$1"
    local cmd="$2"
    local output
    if output=$(eval "$cmd" 2>&1); then
        echo "  [PASS] $name"
        PASS=$((PASS + 1))
    else
        echo "  [FAIL] $name"
        echo "         Error: $output"
        FAIL=$((FAIL + 1))
    fi
}

echo "=== MLOps Pipeline Verification ==="
echo ""

echo "[Phase 1: Infrastructure — Services Health]"
check "PostgreSQL healthy" "docker compose exec postgres pg_isready -U ${POSTGRES_USER:-mlops}"
check "MinIO healthy" "curl -sf http://localhost:${MINIO_API_PORT:-9000}/minio/health/live"
check "MLflow healthy" "curl -sf http://localhost:${MLFLOW_PORT:-5000}/health"
check "Prefect healthy" "curl -sf http://localhost:${PREFECT_PORT:-4200}/api/health"
check "Redis healthy" "docker compose exec redis redis-cli ping"

echo ""
echo "[Phase 1: Infrastructure — PostgreSQL Databases]"
check "mlflow database exists" "docker compose exec postgres psql -U ${POSTGRES_USER:-mlops} -lqt | grep -q mlflow"
check "prefect database exists" "docker compose exec postgres psql -U ${POSTGRES_USER:-mlops} -lqt | grep -q prefect"

echo ""
echo "[Phase 1: Infrastructure — MinIO Buckets]"
check "mlflow-artifacts bucket" "docker compose run --rm --entrypoint sh minio-init -c 'mc alias set myminio http://minio:9000 \${MINIO_ROOT_USER} \${MINIO_ROOT_PASSWORD} && mc ls myminio/mlflow-artifacts'"
check "dvc-storage bucket" "docker compose run --rm --entrypoint sh minio-init -c 'mc alias set myminio http://minio:9000 \${MINIO_ROOT_USER} \${MINIO_ROOT_PASSWORD} && mc ls myminio/dvc-storage'"
check "model-registry bucket" "docker compose run --rm --entrypoint sh minio-init -c 'mc alias set myminio http://minio:9000 \${MINIO_ROOT_USER} \${MINIO_ROOT_PASSWORD} && mc ls myminio/model-registry'"
check "prediction-logs bucket" "docker compose run --rm --entrypoint sh minio-init -c 'mc alias set myminio http://minio:9000 \${MINIO_ROOT_USER} \${MINIO_ROOT_PASSWORD} && mc ls myminio/prediction-logs'"
check "drift-reports bucket" "docker compose run --rm --entrypoint sh minio-init -c 'mc alias set myminio http://minio:9000 \${MINIO_ROOT_USER} \${MINIO_ROOT_PASSWORD} && mc ls myminio/drift-reports'"

echo ""
echo "[Phase 5: Serving]"
check "API /health" "curl -sf http://localhost:${API_PORT:-8000}/health"
check "Nginx /nginx/health" "curl -sf http://localhost:${NGINX_PORT:-80}/nginx/health"

echo ""
echo "[Phase 6: Monitoring]"
check "Prometheus healthy" "curl -sf http://localhost:${PROMETHEUS_PORT:-9090}/-/healthy"
check "Pushgateway healthy" "curl -sf http://localhost:${PUSHGATEWAY_PORT:-9091}/-/healthy"
check "Grafana healthy" "curl -sf http://localhost:${GRAFANA_PORT:-3000}/api/health"
check "API /metrics endpoint" "curl -sf http://localhost:${API_PORT:-8000}/metrics | grep -q http_request"

echo ""
echo "[UI Accessibility]"
check "MLflow UI (localhost:${MLFLOW_PORT:-5000})" "curl -sf http://localhost:${MLFLOW_PORT:-5000}/"
check "Prefect UI (localhost:${PREFECT_PORT:-4200})" "curl -sf http://localhost:${PREFECT_PORT:-4200}/api/health"
check "MinIO Console (localhost:${MINIO_CONSOLE_PORT:-9001})" "curl -sf http://localhost:${MINIO_CONSOLE_PORT:-9001}/"
check "Prometheus UI (localhost:${PROMETHEUS_PORT:-9090})" "curl -sf http://localhost:${PROMETHEUS_PORT:-9090}/graph"
check "Grafana UI (localhost:${GRAFANA_PORT:-3000})" "curl -sf http://localhost:${GRAFANA_PORT:-3000}/"

echo ""
echo "=== Results: $PASS passed, $FAIL failed ==="

if [ "$FAIL" -gt 0 ]; then
    echo "Some checks failed. Run 'make logs SERVICE=<name>' to investigate."
    exit 1
fi

echo "All checks passed!"
