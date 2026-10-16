#!/usr/bin/env bash
# Prove a backup can be restored: download it, load it into a scratch
# database, check the main tables, then drop the scratch database.
#
#   scripts/restore-check.sh            # newest backup
#   scripts/restore-check.sh <s3-key>   # a specific backup
#
# The live database is never touched; the restore goes into
# itsm_restore_check, which is dropped at the end even on failure.

set -Eeuo pipefail
umask 077

PROJECT_DIR=${PROJECT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}
# shellcheck source=scripts/lib.sh
. "$PROJECT_DIR/scripts/lib.sh"

load_settings POSTGRES_USER BACKUP_S3_BUCKET
prefix=${BACKUP_S3_PREFIX:-itsm}
scratch=itsm_restore_check
file=$(mktemp "${TMPDIR:-/tmp}/itsm-restore.XXXXXX")

cleanup() {
	rm -f "$file"
	db_exec psql -q -U "$POSTGRES_USER" -d postgres -c "DROP DATABASE IF EXISTS $scratch" >/dev/null 2>&1 || true
}
trap cleanup EXIT
trap 'log "FAILED at line $LINENO: $BASH_COMMAND"' ERR

key=${1:-}
if [ -z "$key" ]; then
	key=$(aws s3api list-objects-v2 --bucket "$BACKUP_S3_BUCKET" --prefix "$prefix/" \
		--query 'sort_by(Contents, &LastModified)[-1].Key' --output text)
fi
if [ -z "$key" ] || [ "$key" = "None" ]; then
	log "no backups found under s3://$BACKUP_S3_BUCKET/$prefix/"
	exit 1
fi

log "downloading s3://$BACKUP_S3_BUCKET/$key"
aws s3 cp "s3://$BACKUP_S3_BUCKET/$key" "$file" --only-show-errors --no-progress
gzip -t "$file"

log "restoring into scratch database $scratch"
db_exec psql -q -U "$POSTGRES_USER" -d postgres -c "SET client_min_messages = warning" -c "DROP DATABASE IF EXISTS $scratch" >/dev/null
db_exec psql -q -U "$POSTGRES_USER" -d postgres -c "CREATE DATABASE $scratch" >/dev/null
gzip -dc "$file" | db_exec psql -q -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$scratch" >/dev/null

counts=$(db_exec psql -At -U "$POSTGRES_USER" -d "$scratch" -c "
	SELECT concat_ws(' ',
		'users=' || (SELECT count(*) FROM users),
		'employees=' || (SELECT count(*) FROM employees),
		'assets=' || (SELECT count(*) FROM assets),
		'tickets=' || (SELECT count(*) FROM tickets),
		'migration=' || (SELECT version_num FROM alembic_version))")
log "restored: $counts"
case "$counts" in
	*"users=0 "* | *"migration=" | "")
		log "restored data looks empty or has no migration version"
		exit 1
		;;
esac
log "restore check passed"
