# shellcheck shell=bash
# Shared helpers for the server scripts. Sourced, not run.

log() {
	printf '%s %s\n' "$(date '+%Y-%m-%d %H:%M:%S %Z')" "$*" >&2
}

# Read only the named keys from .env. The file is parsed line by line, never
# executed, so a stray command in .env cannot run as part of a backup.
load_settings() {
	local env_file=${ENV_FILE:-$PROJECT_DIR/.env} key line value
	if [ ! -r "$env_file" ]; then
		log "cannot read $env_file"
		exit 1
	fi
	for key in "$@" BACKUP_S3_PREFIX APP_ENV; do
		line=$(grep -E "^${key}=" "$env_file" | tail -n 1 || true)
		value=${line#*=}
		# Drop optional surrounding quotes.
		value=${value%\"}; value=${value#\"}; value=${value%\'}; value=${value#\'}
		if [ -z "${!key:-}" ] && [ -n "$value" ]; then
			printf -v "$key" '%s' "$value"
		fi
	done
	for key in "$@"; do
		if [ -z "${!key:-}" ]; then
			log "$key is not set in $env_file"
			exit 1
		fi
	done
}

# Run a PostgreSQL client command in the db container (default) or, when
# DB_EXEC is set to an empty value, with the local client tools.
db_exec() {
	if [ "${DB_EXEC+set}" = set ] && [ -z "$DB_EXEC" ]; then
		"$@"
		return
	fi
	if [ -n "${DB_EXEC:-}" ]; then
		local -a exec_prefix
		read -ra exec_prefix <<< "$DB_EXEC"
		"${exec_prefix[@]}" "$@"
		return
	fi
	docker compose -f "$PROJECT_DIR/docker-compose.prod.yml" exec -T db "$@"
}
