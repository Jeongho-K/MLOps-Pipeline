#!/usr/bin/env bash
# Update Nginx upstream configuration for canary deployment.
# Usage: ./scripts/update_nginx_config.sh <champion_weight> <canary_weight> [nginx_container]
#
# Examples:
#   ./scripts/update_nginx_config.sh 9 1          # Start canary (90/10 split)
#   ./scripts/update_nginx_config.sh 10 0          # Full rollout (champion only)

set -euo pipefail

CHAMPION_WEIGHT="${1:?Usage: $0 <champion_weight> <canary_weight> [nginx_container]}"
CANARY_WEIGHT="${2:?Usage: $0 <champion_weight> <canary_weight> [nginx_container]}"
NGINX_CONTAINER="${3:-nginx}"
UPSTREAM_PATH="/etc/nginx/conf.d/upstream.conf"

if [ "$CANARY_WEIGHT" -gt 0 ]; then
    CONFIG="upstream api_backend {
    server api:8000 weight=${CHAMPION_WEIGHT};
    server api-canary:8000 weight=${CANARY_WEIGHT};
}
"
else
    CONFIG="upstream api_backend {
    server api:8000;
}
"
fi

# Write config to temp file and copy into container
TMPFILE=$(mktemp)
echo "$CONFIG" > "$TMPFILE"

docker cp "$TMPFILE" "${NGINX_CONTAINER}:${UPSTREAM_PATH}"
docker exec "$NGINX_CONTAINER" nginx -s reload
rm -f "$TMPFILE"

echo "Nginx updated: champion_weight=${CHAMPION_WEIGHT}, canary_weight=${CANARY_WEIGHT}"
