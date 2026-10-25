#!/bin/sh
# Runs once, on the first start of an empty data volume (production and local stacks).
# POSTGRES_USER / POSTGRES_DB (ihsp) are created by the image; Hydra gets its own role
# and database so a leaked Hydra DSN cannot read application data.
# Needs HYDRA_DB_PASSWORD in the container environment.
set -eu

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres \
    -v hydra_password="$HYDRA_DB_PASSWORD" <<'SQL'
CREATE ROLE hydra LOGIN PASSWORD :'hydra_password';
CREATE DATABASE hydra OWNER hydra;
SQL
