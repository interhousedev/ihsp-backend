#!/bin/sh
# Runs INSIDE a throwaway redis container (sh, not bash): loads /restore/redis.rdb into an
# empty /data and turns it into the AOF that the real server reads at start. With
# appendonly yes Redis ignores dump.rdb, so: start with AOF off, CONFIG SET appendonly yes
# (Redis rewrites the AOF from memory), wait for the rewrite and its manifest, stop.
# Used by restore.sh and migrate_target.sh: dc run ... --entrypoint sh redis -c "$(cat ...)".
set -eu
# The two paths can be moved for tests; in the container they are /data and /restore.
data=${IHSP_REDIS_DATA:-/data}
restore=${IHSP_REDIS_RESTORE:-/restore}
fail() { echo "redis restore: $*" >&2; redis-cli shutdown nosave > /dev/null 2>&1 || true; exit 1; }
rm -rf "$data/appendonlydir" "$data/dump.rdb"
cp "$restore/redis.rdb" "$data/dump.rdb"
redis-server --appendonly no --daemonize yes --dir "$data" --requirepass "$REDIS_PASSWORD" > /dev/null
export REDISCLI_AUTH="$REDIS_PASSWORD"
up=0
for _ in $(seq 1 30); do
    if redis-cli ping 2> /dev/null | grep -q '^PONG$'; then up=1; break; fi
    sleep 1
done
[ "$up" = 1 ] || fail "the server did not answer PONG within 30 s"
redis-cli INFO persistence | grep -q '^loading:0' || fail "the RDB is still loading"
keys=$(redis-cli DBSIZE | tr -d '\r')
[ "$(redis-cli CONFIG SET appendonly yes | tr -d '\r')" = OK ] || fail "CONFIG SET appendonly yes failed"
done_=0
for _ in $(seq 1 120); do
    info=$(redis-cli INFO persistence | tr -d '\r')
    if echo "$info" | grep -q '^aof_rewrite_in_progress:0' \
        && echo "$info" | grep -q '^aof_rewrite_scheduled:0' \
        && echo "$info" | grep -q '^aof_last_bgrewrite_status:ok' \
        && ls "$data"/appendonlydir/*.manifest > /dev/null 2>&1; then
        done_=1; break
    fi
    sleep 1
done
[ "$done_" = 1 ] || fail "the AOF rewrite did not finish within 120 s (no manifest)"
redis-cli shutdown nosave > /dev/null 2>&1 || true
echo "redis restore: $keys keys loaded, AOF written" >&2
