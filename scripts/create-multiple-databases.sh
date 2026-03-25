#!/bin/bash
# Create multiple databases from POSTGRES_MULTIPLE_DATABASES env var.
# This script is mounted into /docker-entrypoint-initdb.d/ and runs
# automatically on first PostgreSQL container start (empty data volume).
#
# NOTE: This script only runs when the data volume is empty (first start).
# If you add a new database later, you must either:
#   1. Run `docker compose down -v` to reset volumes (loses all data), or
#   2. Manually create the database with `docker compose exec postgres psql -U mlops -c "CREATE DATABASE newdb;"`

set -e
set -u

if [ -n "$POSTGRES_MULTIPLE_DATABASES" ]; then
    echo "Creating multiple databases: $POSTGRES_MULTIPLE_DATABASES"
    for db in $(echo "$POSTGRES_MULTIPLE_DATABASES" | tr ',' ' '); do
        # Check if database already exists before creating
        EXISTS=$(psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" -tAc \
            "SELECT 1 FROM pg_database WHERE datname = '$db'")
        if [ "$EXISTS" = "1" ]; then
            echo "  Database '$db' already exists. Skipping."
        else
            echo "  Creating database '$db'..."
            psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" <<-EOSQL
                CREATE DATABASE "$db";
                GRANT ALL PRIVILEGES ON DATABASE "$db" TO "$POSTGRES_USER";
EOSQL
            echo "  Database '$db' created."
        fi
    done
    echo "Multiple databases created successfully."
fi
