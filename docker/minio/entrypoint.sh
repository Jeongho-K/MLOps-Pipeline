#!/bin/sh
set -e

# Start MinIO server in background
minio server /data --console-address ":9001" &
MINIO_PID=$!

# Wait for server to be ready
echo "Waiting for MinIO server to start..."
for i in $(seq 1 30); do
    if curl -sf http://localhost:9000/minio/health/live > /dev/null 2>&1; then
        echo "MinIO server is ready."
        break
    fi
    if [ "$i" -eq 30 ]; then
        echo "ERROR: MinIO server did not start within 30s."
        exit 1
    fi
    sleep 1
done

# Create buckets using mc CLI
echo "Creating buckets..."
mc alias set local http://localhost:9000 "${MINIO_ROOT_USER}" "${MINIO_ROOT_PASSWORD}"
mc mb --ignore-existing local/mlflow-artifacts
mc mb --ignore-existing local/dvc-storage
mc mb --ignore-existing local/model-registry
mc mb --ignore-existing local/prediction-logs
mc mb --ignore-existing local/drift-reports
echo "All buckets created successfully."

# Bring MinIO server to foreground
wait $MINIO_PID
