# MLflow server with PostgreSQL and S3 (MinIO) support
# The official ghcr.io/mlflow/mlflow image does not include psycopg2 or boto3,
# which are required for PostgreSQL backend store and S3 artifact store.

FROM ghcr.io/mlflow/mlflow:v3.10.1

RUN pip install --no-cache-dir psycopg2-binary boto3

# Create non-root user
RUN groupadd -r mlflow && useradd -r -g mlflow -d /app mlflow
USER mlflow

EXPOSE 5000

ENTRYPOINT ["mlflow", "server"]
