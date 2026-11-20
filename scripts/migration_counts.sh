#!/usr/bin/env bash
# Row counts of every store of this install, as TSV: store<TAB>item<TAB>value.
# migrate_runner.sh writes it on the source before the transfer; migrate_target.sh writes
# it on the target after the restore, and the two must match.
#   ihsp, hydra, bugsink  exact row count of every table, summed per schema (postgres)
#   redis                 keys (DBSIZE)
#   s3                    objects in the bundled store, or "external" for another endpoint
#   vault                 sealed state only: the raw snapshot has no rows to count
#
# Usage: IHSP_ROOT=/opt/ihsp scripts/migration_counts.sh
set -euo pipefail

ROOT=${IHSP_ROOT:-/opt/ihsp}
cd "$ROOT"

dc() { docker compose --env-file "$ROOT/.env.prod" -f "$ROOT/materials/docker-compose.prod.yaml" "$@"; }
env_value() { sed -n "s/^$1=//p" "$ROOT/.env.prod" | tail -n 1 | tr -d "\"'"; }

# Exact count(*) per table (query_to_xml runs the count, information_schema lists tables).
ROWS_SQL="SELECT table_schema, sum((xpath('/row/c/text()', query_to_xml(
    format('SELECT count(*) AS c FROM %I.%I', table_schema, table_name), false, true, '')))[1]::text::bigint)
    FROM information_schema.tables
    WHERE table_type = 'BASE TABLE' AND table_schema NOT IN ('pg_catalog', 'information_schema')
    GROUP BY table_schema ORDER BY table_schema"

# pg_rows STORE SERVICE DB USER [compose args...]: one line per schema of DB.
pg_rows() {
    local store=$1 service=$2 db=$3 user=$4
    shift 4
    dc "$@" exec -T "$service" psql -U "$user" -d "$db" -At -F '|' -c "$ROWS_SQL" \
        | tr '|' '\t' | sed "s/^/$store\t/"
}

pg_rows ihsp postgres ihsp ihsp
pg_rows hydra postgres hydra ihsp

if [ "$(env_value BUGSINK_DB_MODE)" = dedicated ]; then
    pg_rows bugsink bugsink-db bugsink bugsink --profile bugsink-dedicated
elif [ "$(dc exec -T postgres psql -U ihsp -d postgres -tAc \
    "SELECT 1 FROM pg_database WHERE datname = 'bugsink'" | tr -d '\r')" = 1 ]; then
    pg_rows bugsink postgres bugsink ihsp
fi

printf 'redis\tkeys\t%s\n' "$(dc exec -T redis redis-cli DBSIZE | tr -dc '0-9')"

url=$(env_value IHSP_S3__ENDPOINT_URL)
case "$url" in
    http://s3 | http://s3/ | http://s3:* | https://s3 | https://s3/ | https://s3:*)
        printf 's3\tobjects\t%s\n' \
            "$(dc exec -T s3 sh -c 'find /data -type f | wc -l' | tr -dc '0-9')" ;;
    *) printf 's3\tobjects\texternal\n' ;;
esac

printf 'vault\tsealed\t%s\n' \
    "$(dc exec -T vault vault status 2> /dev/null | awk '$1 == "Sealed" { print $2 }' || true)"
