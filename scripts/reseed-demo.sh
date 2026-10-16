#!/usr/bin/env bash
# Public demo only: put the demo data back every night, so changes made by
# visitors do not pile up. Does nothing unless APP_ENV=demo (and the seed
# itself refuses to run in production).

set -Eeuo pipefail

PROJECT_DIR=${PROJECT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}
# shellcheck source=scripts/lib.sh
. "$PROJECT_DIR/scripts/lib.sh"

# No setting is required here; APP_ENV is read if present.
# shellcheck disable=SC2119
load_settings
if [ "${APP_ENV:-}" != "demo" ]; then
	log "APP_ENV is '${APP_ENV:-}', not demo: nothing to do"
	exit 0
fi
log "re-seeding demo data"
docker compose -f "$PROJECT_DIR/docker-compose.prod.yml" exec -T api python -m app.seed
log "demo data restored"
