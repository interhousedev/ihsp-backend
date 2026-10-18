#!/bin/sh
# Runs once, on the first start of an empty data volume (production stack).
# Bugsink (error tracking) gets its own role and database, so a leaked Bugsink DSN cannot
# read application data. Needs BUGSINK_DB_PASSWORD in the container environment.
set -eu

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres \
    -v bugsink_password="$BUGSINK_DB_PASSWORD" <<'SQL'
CREATE ROLE bugsink LOGIN PASSWORD :'bugsink_password';
CREATE DATABASE bugsink OWNER bugsink;
SQL
