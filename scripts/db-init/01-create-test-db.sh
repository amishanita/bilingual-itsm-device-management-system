#!/bin/sh
# Creates the separate test database the first time the PostgreSQL volume is initialised.
# pytest only runs against a database whose name ends with _test.
set -eu

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
	CREATE DATABASE "${POSTGRES_DB}_test" OWNER "$POSTGRES_USER";
EOSQL
