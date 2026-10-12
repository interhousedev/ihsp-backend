#!/usr/bin/env bash
# Build and start the whole IHSP stack on this machine (project `ihsp-local`):
# backend and web images, every service of materials/docker-compose.local.yaml, the Hydra
# clients and the demo data.
#
# Usage: scripts/local_up.sh [--no-build] [--full-build] [--no-seed]
#   --no-build     reuse the images from the last run (and the web apps built on the host)
#   --full-build   build the web image the long way: `next build` of all seven apps inside
#                  Docker (iht-web deploy/Dockerfile). Needs a Docker VM with plenty of memory
#                  and nothing else heavy running; the default does not.
#   --no-seed      skip `python -m app seed-demo`
# By default the web apps are built on the host, one at a time (`bun run build`, so Bun
# must be installed), and packed into the image by iht-web deploy/Dockerfile.prebuilt.
# Optional settings (fake modes, ports, domain) go into .env.local; see
# materials/.env.local.sample.
set -euo pipefail
cd "$(dirname "$0")/.."

build=1
full_build=0
seed=1
for arg in "$@"; do
    case "$arg" in
        --no-build) build=0 ;;
        --full-build) full_build=1 ;;
        --no-seed) seed=0 ;;
        -h | --help)
            sed -n '2,/^set -euo/{/^set -euo/!p;}' "$0"
            exit 0
            ;;
        *)
            echo "unknown argument: $arg" >&2
            exit 2
            ;;
    esac
done

compose_file=materials/docker-compose.local.yaml
web_dir=${IHSP_WEB_DIR:-../iht-web}
if [ ! -d "$web_dir/deploy" ]; then
    echo "web checkout not found at $web_dir: clone the iht-web repo next to this one or set IHSP_WEB_DIR" >&2
    exit 1
fi
# The compose file resolves its build context relative to materials/.
case "$web_dir" in
    /*) export IHSP_WEB_DIR="$web_dir" ;;
    *) export IHSP_WEB_DIR="$(cd "$web_dir" && pwd)" ;;
esac
web_apps=(id sp staff admin lms share library)
if [ "$full_build" -eq 1 ]; then
    export WEB_DOCKERFILE=deploy/Dockerfile
else
    export WEB_DOCKERFILE=deploy/Dockerfile.prebuilt
fi

compose() {
    if [ -f .env.local ]; then
        docker compose --env-file .env.local -f "$compose_file" "$@"
    else
        docker compose -f "$compose_file" "$@"
    fi
}

command -v docker > /dev/null || { echo "docker is not installed" >&2; exit 1; }
docker compose version > /dev/null || { echo "docker compose v2 is required" >&2; exit 1; }

# Development key of identity's JWT-bearer assertions (also used by the Hydra bootstrap).
key=materials/dev-keys/jwt-bearer.pem
if [ ! -f "$key" ]; then
    mkdir -p materials/dev-keys
    openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:2048 -out "$key"
fi
chmod 644 "$key" # a development key: containers run as another uid and must read it

# Build the static exports on the host, one app at a time, so peak memory is one `next build`.
build_web_on_host() {
    command -v bun > /dev/null || {
        echo "bun is not installed (https://bun.sh); install it or use --full-build" >&2
        exit 1
    }
    if [ ! -d "$web_dir/node_modules" ]; then
        echo "==> installing the web dependencies"
        (cd "$web_dir" && bun install --frozen-lockfile)
    fi
    local app
    for app in "${web_apps[@]}"; do
        echo "==> building the web app: $app"
        (cd "$web_dir" && NEXT_TELEMETRY_DISABLED=1 bun run --filter "./apps/$app" build)
    done
    echo "==> adding the per-page script policy (CSP meta)"
    (cd "$web_dir" && bun deploy/csp-hash.ts > /dev/null)
}

if [ "$build" -eq 1 ]; then
    if [ "$full_build" -eq 0 ]; then
        build_web_on_host
    fi
    echo "==> building the backend and web images (web: $WEB_DOCKERFILE)"
    compose build migrate web
fi

echo "==> starting the stack"
compose up -d --wait
# The edge config is bind-mounted: a running nginx keeps the old upstreams until it reloads.
compose exec -T nginx nginx -s reload

echo "==> registering the OAuth clients in Hydra"
compose run --rm bootstrap

if [ "$seed" -eq 1 ]; then
    echo "==> seeding demo data"
    compose exec -T api python -m app seed-demo
fi

# Values for the printout and the smoke checks.
domain=localhost
suffix=
if [ -f .env.local ]; then
    domain=$(sed -n 's/^LOCAL_DOMAIN=//p' .env.local | tail -n 1)
    suffix=$(sed -n 's/^LOCAL_PORT_SUFFIX=//p' .env.local | tail -n 1)
    domain=${domain:-localhost}
fi
port=${suffix#:}
port=${port:-80}
mailpit_port=
if [ -f .env.local ]; then
    mailpit_port=$(sed -n 's/^LOCAL_MAILPIT_PORT=//p' .env.local | tail -n 1)
fi
mailpit_port=${mailpit_port:-8026}

# `--resolve` makes the checks independent of how this machine resolves *.localhost.
check() {
    local host=$1 path=$2 expect=$3 code
    code=$(curl -s -o /dev/null -w '%{http_code}' --resolve "$host:$port:127.0.0.1" \
        "http://$host$suffix$path" || true)
    if [ "$code" = "$expect" ]; then
        echo "  ok   $host$path -> $code"
    else
        echo "  FAIL $host$path -> $code (expected $expect)" >&2
        failed=1
    fi
}

failed=0
echo "==> checking the edge"
check "api.$domain" /health 200
check "id.$domain" /.well-known/openid-configuration 200
check "sp.$domain" / 200
check "app.$domain" / 200
check "library.$domain" / 200
check "library.$domain" /env.js 200
check "s.$domain" /ai/view/ 200

cat << EOF

IHSP is running.

  Student app    http://sp.$domain$suffix/
  App (PWA)      http://app.$domain$suffix/      (installable: open it on a phone)
  Teacher app    http://staff.$domain$suffix/
  Admin          http://admin.$domain$suffix/
  LMS            http://lms.$domain$suffix/
  Library        http://library.$domain$suffix/
  Login (id)     http://id.$domain$suffix/
  API            http://api.$domain$suffix/      (health: /health)
  MCP            http://mcp.$domain$suffix/
  Room pages     http://$domain$suffix/r/<slug>
  Mailpit        http://127.0.0.1:$mailpit_port/   (login codes and outgoing mail)

Demo logins (python -m app seed-demo):
  admin    admin.ihsp                           AdminDemo1     (the second factor code arrives in Mailpit)
  teacher  usmonov.bobur, karimova.nodira, ...  TeacherDemo1   (five demo teachers)
  student  abdullayev.alisher, ergashev.gulnora StudentDemo1   (the fake-EMIS accounts student01 and student16)

Logs:   docker compose -f $compose_file logs -f <service>
Stop:   scripts/local_down.sh        (add --wipe to delete the data)
EOF

exit "$failed"
