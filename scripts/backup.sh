#!/usr/bin/env bash
# Daily database backup: pg_dump from the db container, gzip, upload to S3.
#
#   scripts/backup.sh
#
# Settings come from the project .env (POSTGRES_DB, POSTGRES_USER,
# BACKUP_S3_BUCKET, BACKUP_S3_PREFIX). AWS credentials come from the normal AWS
# CLI configuration of the user running cron (~/.aws), never from .env.
# Exits non-zero if any step fails; the local dump is always removed.
#
# DB_EXEC is the command prefix that reaches PostgreSQL. It defaults to the
# production container; set it to an empty value to use local pg_dump/psql
# with the usual PGHOST/PGPORT variables (used when testing the scripts).

set -Eeuo pipefail
umask 077

PROJECT_DIR=${PROJECT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}
# shellcheck source=scripts/lib.sh
. "$PROJECT_DIR/scripts/lib.sh"

load_settings POSTGRES_DB POSTGRES_USER BACKUP_S3_BUCKET
prefix=${BACKUP_S3_PREFIX:-itsm}
stamp=$(date -u +%Y%m%dT%H%M%SZ)
key="$prefix/$(date -u +%Y/%m)/itsm-$stamp.sql.gz"
dump=$(mktemp "${TMPDIR:-/tmp}/itsm-backup.XXXXXX")
trap 'rm -f "$dump"' EXIT
trap 'log "FAILED at line $LINENO: $BASH_COMMAND"' ERR

log "dumping database $POSTGRES_DB"
# pipefail makes a pg_dump failure fail the whole pipeline, not just gzip.
db_exec pg_dump --no-owner --no-privileges -U "$POSTGRES_USER" -d "$POSTGRES_DB" | gzip -9 > "$dump"

gzip -t "$dump"
# pg_dump writes this line last; without it the dump was cut short.
if ! gzip -dc "$dump" | tail -n 5 | grep -q "PostgreSQL database dump complete"; then
	log "dump is incomplete"
	exit 1
fi
size=$(wc -c < "$dump" | tr -d ' ')
log "dump ok ($size bytes), uploading to s3://$BACKUP_S3_BUCKET/$key"

aws s3 cp "$dump" "s3://$BACKUP_S3_BUCKET/$key" --sse AES256 --only-show-errors --no-progress

remote=$(aws s3api head-object --bucket "$BACKUP_S3_BUCKET" --key "$key" --query ContentLength --output text)
if [ "$remote" != "$size" ]; then
	log "uploaded size $remote does not match local size $size"
	exit 1
fi
log "backup complete: s3://$BACKUP_S3_BUCKET/$key"
