#!/bin/sh
# Runs once, on the first start of an empty data volume (production stack).
# Bugsink (error tracking) gets its own role and database, so a leaked Bugsink DSN cannot
# read application data. Needs BUGSINK_DB_PASSWORD in the container environment.
# In dedicated mode (BUGSINK_DB_MODE=dedicated) Bugsink has its own database server, so
# nothing is created here and the script exits 0.
set -eu

if [ "${BUGSINK_DB_MODE:-main}" != "main" ]; then
    echo "bugsink: BUGSINK_DB_MODE=${BUGSINK_DB_MODE}, skipping the main-database role" >&2
    exit 0
fi
: "${BUGSINK_DB_PASSWORD:?BUGSINK_DB_PASSWORD is required when BUGSINK_DB_MODE is main}"

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres \
    -v bugsink_password="$BUGSINK_DB_PASSWORD" <<'SQL'
CREATE ROLE bugsink LOGIN PASSWORD :'bugsink_password';
CREATE DATABASE bugsink OWNER bugsink;
SQL
