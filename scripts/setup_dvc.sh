#!/bin/bash
# Initialize DVC and configure MinIO as remote storage.
# Run once after `uv sync` and `make up`.

set -eu

echo "=== DVC Setup ==="

# Initialize DVC if not already initialized
if [ ! -d ".dvc" ]; then
    echo "[1/4] Initializing DVC..."
    dvc init
else
    echo "[1/4] DVC already initialized. Skipping."
fi

# Configure MinIO as the default remote
echo "[2/4] Configuring MinIO remote..."
if ! output=$(dvc remote add -d minio-remote s3://dvc-storage 2>&1); then
    if echo "$output" | grep -q "already exists"; then
        echo "  Remote 'minio-remote' already exists. Updating configuration."
        dvc remote modify minio-remote url s3://dvc-storage
    else
        echo "ERROR: Failed to add DVC remote: $output" >&2
        exit 1
    fi
fi

dvc remote modify minio-remote endpointurl "http://localhost:${MINIO_API_PORT:-9000}"
dvc remote modify minio-remote access_key_id "${MINIO_ROOT_USER:-minioadmin}"
dvc remote modify minio-remote secret_access_key "${MINIO_ROOT_PASSWORD:-minioadmin123}"
dvc remote modify minio-remote use_ssl false

# Verify MinIO connectivity
echo "[3/4] Verifying MinIO connectivity..."
if ! curl -sf "http://localhost:${MINIO_API_PORT:-9000}/minio/health/live" > /dev/null 2>&1; then
    echo "WARNING: MinIO is not reachable at http://localhost:${MINIO_API_PORT:-9000}" >&2
    echo "  Make sure to run 'make up' before using DVC push/pull." >&2
else
    echo "  MinIO is reachable."
fi

echo "[4/4] DVC configuration complete."
echo ""
echo "  Remote: minio-remote → s3://dvc-storage"
echo "  Endpoint: http://localhost:${MINIO_API_PORT:-9000}"
echo ""
echo "Usage:"
echo "  dvc add data/raw/<dataset>     # Track dataset"
echo "  dvc push                        # Upload to MinIO"
echo "  dvc pull                        # Download from MinIO"
