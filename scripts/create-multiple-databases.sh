#!/bin/bash
# Create multiple databases from POSTGRES_MULTIPLE_DATABASES env var.
# This script is mounted into /docker-entrypoint-initdb.d/ and runs
# automatically on first PostgreSQL container start (empty data volume).

set -e
set -u

if [ -n "$POSTGRES_MULTIPLE_DATABASES" ]; then
    echo "Creating multiple databases: $POSTGRES_MULTIPLE_DATABASES"
    for db in $(echo "$POSTGRES_MULTIPLE_DATABASES" | tr ',' ' '); do
        echo "  Creating database '$db'..."
        psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" <<-EOSQL
            CREATE DATABASE $db;
            GRANT ALL PRIVILEGES ON DATABASE $db TO $POSTGRES_USER;
EOSQL
        echo "  Database '$db' created."
    done
    echo "Multiple databases created successfully."
fi
