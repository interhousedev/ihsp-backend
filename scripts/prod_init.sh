#!/usr/bin/env bash
# First-time setup of a production server, and the few recurring jobs around it.
# Run it on the server, in the deploy directory (default /opt/ihsp, see cloud_deploy.sh):
#
#   scripts/prod_init.sh env             create .env.prod from the sample, generate secrets and keys
#   scripts/prod_init.sh init            everything below, in order (the default)
#   scripts/prod_init.sh vault           initialise Vault, unseal it, enable Transit/KV/AppRole,
#                                        write the policies and store the AppRole ids in .env.prod
#   scripts/prod_init.sh unseal          unseal Vault after a restart or reboot
#   scripts/prod_init.sh certs           issue the Let's Encrypt certificate and start nginx
#   scripts/prod_init.sh hydra           start Hydra and register the OAuth clients
#   scripts/prod_init.sh s3              create/configure the S3 bucket (CORS, lifecycle)
#   scripts/prod_init.sh admin           create the first administrator (prints an activation link)
#
# Environment: ACME_STAGING=1 uses Let's Encrypt's staging server (for rehearsals).
# Idempotent: every step can be repeated.
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT"

ENV_FILE=.env.prod
COMPOSE_FILE=materials/docker-compose.prod.yaml
VAULT_KEYS=secrets/vault-init.txt

# Variables that must be generated when they still hold the sample's placeholder.
GENERATED=(
    POSTGRES_PASSWORD HYDRA_DB_PASSWORD REDIS_PASSWORD
    HYDRA_SECRET_SYSTEM HYDRA_SECRET_COOKIE HYDRA_SECRET_PAGINATION
    IHSP_TOKENS__SERVICE_TOKEN IHSP_TELEGRAM__WEBHOOK_SECRET IHSP_HYDRA__MINIAPP_CLIENT_SECRET
)

say() { printf '==> %s\n' "$*"; }
die() { printf 'error: %s\n' "$*" >&2; exit 1; }

dc() { docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" "$@"; }

# get_env KEY: the last value of KEY in .env.prod (empty when absent).
get_env() { sed -n "s/^$1=//p" "$ENV_FILE" | tail -n 1; }

# set_env KEY VALUE: replace the KEY= line or append it (portable: no sed -i).
set_env() {
    local key=$1 value=$2 tmp
    tmp=$(mktemp "$ENV_FILE.XXXXXX")
    awk -v key="$key" -v value="$value" '
        BEGIN { FS = OFS = "="; done = 0 }
        $1 == key { print key "=" value; done = 1; next }
        { print }
        END { if (!done) print key "=" value }
    ' "$ENV_FILE" > "$tmp"
    chmod 600 "$tmp"
    mv "$tmp" "$ENV_FILE"
}

# own_for_containers FILE: readable only by the uid of the containers (10001). Needs root or
# passwordless sudo; otherwise the file is left world-readable inside the mode-700 directory.
own_for_containers() {
    if [ "$(id -u)" = 0 ]; then
        chown 10001:10001 "$1" && chmod 400 "$1"
    elif sudo -n true 2> /dev/null; then
        sudo chown 10001:10001 "$1" && sudo chmod 400 "$1"
    else
        chmod 644 "$1"
        echo "note: no root or sudo; $1 stays mode 644 (owned by $(id -un)) inside the mode-700 directory" >&2
    fi
}

need_env_file() { [ -f "$ENV_FILE" ] || die "$ENV_FILE is missing: run scripts/prod_init.sh env first"; }

# Refuse to continue while a required value still says CHANGE_ME.
require_filled() {
    local missing
    missing=$(grep -E '^[A-Za-z0-9_]+=CHANGE_ME' "$ENV_FILE" | cut -d= -f1 | tr '\n' ' ' || true)
    if [ -n "$missing" ]; then
        die "set these values in $ENV_FILE first: $missing"
    fi
}

# --------------------------------------------------------------------------- env
cmd_env() {
    [ -f materials/.env.prod.sample ] || die "run this from a deployed copy that has materials/"
    mkdir -p secrets data/letsencrypt data/certbot-www data/mail-tls backups
    chmod 700 secrets data backups

    if [ ! -f "$ENV_FILE" ]; then
        cp materials/.env.prod.sample "$ENV_FILE"
        chmod 600 "$ENV_FILE"
        say "created $ENV_FILE"
    fi
    local key
    for key in "${GENERATED[@]}"; do
        if [ "$(get_env "$key")" = "CHANGE_ME_GENERATED" ]; then
            set_env "$key" "$(openssl rand -hex 32)"
            say "generated $key"
        fi
    done

    # identity signs JWT-bearer assertions with this key (the worker is given it too);
    # no other process gets it. The containers run as uid 10001, so the file is handed to
    # that uid and readable by nobody else (compose mounts it as a file secret). Without
    # root (or passwordless sudo) the chown is impossible; the file then stays 644 inside
    # ./secrets, which is itself mode 700.
    if [ ! -f secrets/jwt-bearer.pem ]; then
        (umask 077 && openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:2048 -out secrets/jwt-bearer.pem)
        say "generated secrets/jwt-bearer.pem"
    fi
    own_for_containers secrets/jwt-bearer.pem

    local open
    open=$(grep -E '^[A-Za-z0-9_]+=CHANGE_ME' "$ENV_FILE" | cut -d= -f1 | tr '\n' ' ' || true)
    if [ -n "$open" ]; then
        echo "Still to fill in $ENV_FILE: $open"
    else
        echo "$ENV_FILE is complete."
    fi
}

# ------------------------------------------------------------------------- vault
vault_status_field() {
    # Prints Initialized / Sealed from `vault status` (exit code 2 while sealed is normal).
    dc exec -T vault vault status 2> /dev/null | awk -v f="$1" '$1 == f { print $2 }' || true
}

# The vault CLI only takes an unseal key as an argument (or from a terminal), which would
# put the key in a process list. The HTTP API takes it in a request body instead: the key
# travels over stdin into the container and is posted from there.
unseal_with() {
    local key
    for key in "$@"; do
        printf '%s\n' "$key" | dc exec -T vault sh -c '
            read -r key
            wget -q -O /dev/null --header "Content-Type: application/json" \
                --post-data "{\"key\":\"$key\"}" http://127.0.0.1:8200/v1/sys/unseal'
    done
}

cmd_unseal() {
    need_env_file
    dc up -d vault
    wait_for_vault
    if [ "$(vault_status_field Sealed)" != "true" ]; then
        say "Vault is already unsealed"
        return 0
    fi
    local keys=() key i
    if [ -f "$VAULT_KEYS" ]; then
        while IFS= read -r key; do keys+=("$key"); done \
            < <(sed -n 's/^Unseal Key [0-9]*: //p' "$VAULT_KEYS" | head -n 3)
    else
        for i in 1 2 3; do
            read -r -s -p "Unseal key $i of 3: " key
            echo
            keys+=("$key")
        done
    fi
    unseal_with "${keys[@]}"
    [ "$(vault_status_field Sealed)" = "false" ] || die "Vault is still sealed"
    say "Vault unsealed"
}

wait_for_vault() {
    local i
    for i in $(seq 1 30); do
        if [ -n "$(vault_status_field Initialized)" ]; then
            return 0
        fi
        sleep 2
    done
    die "Vault did not come up: docker compose logs vault"
}

# The root token: from the saved init output, the environment, or a prompt.
vault_root_token() {
    if [ -f "$VAULT_KEYS" ]; then
        sed -n 's/^Initial Root Token: //p' "$VAULT_KEYS"
    elif [ -n "${VAULT_TOKEN:-}" ]; then
        printf '%s' "$VAULT_TOKEN"
    else
        local token
        read -r -s -p "Vault root token: " token
        echo >&2
        printf '%s' "$token"
    fi
}

cmd_vault() {
    need_env_file
    mkdir -p secrets
    say "starting Vault"
    dc up -d --wait vault
    wait_for_vault

    if [ "$(vault_status_field Initialized)" != "true" ]; then
        say "initialising Vault (5 key shares, 3 needed to unseal)"
        (umask 077 && dc exec -T vault vault operator init -key-shares=5 -key-threshold=3 > "$VAULT_KEYS")
        cat << EOF

  Vault is initialised. The 5 unseal keys and the root token are in
      $ROOT/$VAULT_KEYS
  Copy them to a password manager NOW (ideally one key per person), then delete that file
  from the server. Without 3 of the 5 keys a restarted Vault cannot be unsealed and the EMIS
  passwords it holds are lost.

EOF
    fi
    cmd_unseal

    local token
    token=$(vault_root_token)
    [ -n "$token" ] || die "no Vault root token"

    say "enabling Transit, KV v2, AppRole; writing the identity policy and role"
    local out role_id secret_id
    out=$(VAULT_TOKEN=$token dc --profile tools run --rm -T -e VAULT_TOKEN vault-setup \
        python /init/setup.py --print-credentials)
    role_id=$(printf '%s\n' "$out" | sed -n 's/^IHSP_VAULT__ROLE_ID=//p')
    secret_id=$(printf '%s\n' "$out" | sed -n 's/^IHSP_VAULT__SECRET_ID=//p')
    [ -n "$role_id" ] && [ -n "$secret_id" ] || die "vault-setup did not print the AppRole credentials"
    set_env IHSP_VAULT__ROLE_ID "$role_id"
    set_env IHSP_VAULT__SECRET_ID "$secret_id"
    say "stored the identity AppRole credentials in $ENV_FILE"

    say "creating the backup AppRole (may only read Raft snapshots)"
    local backup_ids
    backup_ids=$(VAULT_TOKEN=$token dc exec -T -e VAULT_TOKEN vault sh -c '
        set -e
        vault policy write backup - > /dev/null
        vault write auth/approle/role/backup token_policies=backup token_ttl=10m \
            token_max_ttl=30m secret_id_ttl=0 > /dev/null
        echo "role=$(vault read -field=role_id auth/approle/role/backup/role-id)"
        echo "secret=$(vault write -f -field=secret_id auth/approle/role/backup/secret-id)"
    ' < materials/vault/policies/backup.hcl)
    set_env VAULT_BACKUP_ROLE_ID "$(printf '%s\n' "$backup_ids" | sed -n 's/^role=//p')"
    set_env VAULT_BACKUP_SECRET_ID "$(printf '%s\n' "$backup_ids" | sed -n 's/^secret=//p')"
    say "stored the backup AppRole credentials in $ENV_FILE"
}

# ------------------------------------------------------------------------- certs
cmd_certs() {
    need_env_file
    require_filled
    local domain email storage hosts=() h
    domain=$(get_env DOMAIN)
    email=$(get_env ACME_EMAIL)
    storage=$(get_env STORAGE_PUBLIC_HOST)
    for h in "" id. my. app. staff. admin. lms. lib. s. api. mcp. mail.; do
        hosts+=(-d "$h$domain")
    done
    [ -n "$storage" ] && hosts+=(-d "$storage")

    mkdir -p data/letsencrypt data/certbot-www data/mail-tls
    if [ ! -f "data/letsencrypt/live/$domain/fullchain.pem" ]; then
        say "creating a temporary self-signed certificate so nginx and mail can start"
        dc run --rm --no-deps --entrypoint /bin/sh certbot -c "
            set -e
            d=/etc/letsencrypt/live/$domain
            mkdir -p \$d
            openssl req -x509 -nodes -newkey rsa:2048 -days 7 -subj /CN=$domain \
                -keyout \$d/privkey.pem -out \$d/fullchain.pem 2> /dev/null
            mkdir -p /mail-tls
            cp \$d/fullchain.pem \$d/privkey.pem /mail-tls/
            chown 10001:10001 /mail-tls /mail-tls/*.pem
            chmod 750 /mail-tls
            chmod 640 /mail-tls/fullchain.pem
            chmod 600 /mail-tls/privkey.pem"
    fi

    say "starting the web image and nginx"
    dc up -d --wait web nginx

    if [ ! -f "data/letsencrypt/renewal/$domain.conf" ]; then
        say "requesting the Let's Encrypt certificate (DNS must point every host at this server)"
        # Remove the placeholder: certbot refuses a live/ directory it did not create.
        dc run --rm --no-deps --entrypoint /bin/sh certbot -c "
            rm -rf /etc/letsencrypt/live/$domain /etc/letsencrypt/archive/$domain"
        local staging=()
        [ "${ACME_STAGING:-0}" = "1" ] && staging=(--staging)
        dc run --rm --no-deps --entrypoint certbot certbot certonly --webroot \
            -w /var/www/certbot --cert-name "$domain" "${hosts[@]}" \
            --email "$email" --agree-tos --no-eff-email --non-interactive \
            --deploy-hook /hooks/deploy-hook.sh ${staging[@]+"${staging[@]}"}
        dc exec -T nginx nginx -s reload
    else
        say "a Let's Encrypt certificate for $domain already exists"
    fi
    dc up -d certbot
    print_cron
}

print_cron() {
    cat << EOF

Certificates renew inside the certbot container; nginx and mail must be told afterwards.
Install this cron entry on the host (crontab -e), weekly is enough:

  17 4 * * 1  cd $ROOT && docker compose --env-file $ENV_FILE -f $COMPOSE_FILE exec -T nginx nginx -s reload && docker compose --env-file $ENV_FILE -f $COMPOSE_FILE restart mail

and one for the nightly backup:

  30 2 * * *  cd $ROOT && scripts/backup.sh --keep 14 >> backups/backup.log 2>&1
EOF
}

# ------------------------------------------------------------------------- hydra
cmd_hydra() {
    need_env_file
    say "starting PostgreSQL, Redis and Hydra"
    dc up -d --wait postgres redis
    dc up -d --wait hydra
    say "registering the OAuth clients and the JWT-bearer trust in Hydra"
    [ -f scripts/hydra_bootstrap.py ] || die "scripts/hydra_bootstrap.py is missing (cloud_deploy.sh copies it)"
    dc --profile tools run --rm -T bootstrap
}

# --------------------------------------------------------------------------- s3
cmd_s3() {
    need_env_file
    say "preparing the S3 bucket (CORS for all apps, lifecycle rules)"
    dc --profile tools run --rm -T s3-init
}

# ------------------------------------------------------------------------- admin
cmd_admin() {
    need_env_file
    local login=${1:-} email=${2:-}
    [ -n "$login" ] || read -r -p "Administrator login (for example admin.ihsp): " login
    [ -n "$email" ] || read -r -p "Administrator email: " email
    say "creating the administrator $login"
    dc run --rm --no-deps -T identity python -m app create-user --role admin --login "$login" --email "$email"
    echo "Open the activation link above to set the password and the one-time code device."
}

# -------------------------------------------------------------------------- init
cmd_init() {
    cmd_env
    require_filled
    say "pulling images"
    dc pull --ignore-buildable || die "could not pull the images: run docker login ghcr.io (a private package) and check IMAGE_OWNER (lowercase) and TAG in $ENV_FILE"
    say "starting the data stores"
    dc up -d --wait postgres redis
    cmd_vault
    cmd_certs
    say "applying database migrations"
    dc run --rm --no-deps migrate
    cmd_hydra
    cmd_s3
    say "starting everything"
    dc up -d --wait
    cmd_admin
    cat << EOF

Done. Check:  curl -fsS https://api.$(get_env DOMAIN)/health
Remember: move $VAULT_KEYS off the server, and set the DNS MX record of mail.$(get_env DOMAIN)
(DNS: A/AAAA for the apex and id, my, app, staff, admin, lms, lib, s, api, mcp, mail,
storage; MX 10 mail.<domain>; SPF, DKIM and DMARC TXT records for mail.<domain>).
EOF
}

case "${1:-init}" in
    env) cmd_env ;;
    init) cmd_init ;;
    vault) cmd_vault ;;
    unseal) cmd_unseal ;;
    certs) cmd_certs ;;
    hydra) cmd_hydra ;;
    s3) cmd_s3 ;;
    admin) shift || true; cmd_admin "$@" ;;
    -h | --help | help) sed -n '2,17p' "$0" ;;
    *) die "unknown command: $1 (try --help)" ;;
esac
