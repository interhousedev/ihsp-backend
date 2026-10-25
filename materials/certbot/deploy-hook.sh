#!/bin/sh
# certbot deploy hook (runs after every issue and renewal, inside the certbot container).
# The mail process is not root and cannot read certbot's private key (mode 600), so a copy
# goes to a directory that only the mail container mounts (../data/mail-tls). The copy is
# owned by the uid the mail process runs as (10001, Dockerfile) and readable by
# nobody else; the host path ../data is mode 700 on top of that.
set -eu
mkdir -p /mail-tls
cp "$RENEWED_LINEAGE/fullchain.pem" /mail-tls/fullchain.pem
cp "$RENEWED_LINEAGE/privkey.pem" /mail-tls/privkey.pem
chown 10001:10001 /mail-tls /mail-tls/fullchain.pem /mail-tls/privkey.pem
chmod 750 /mail-tls
chmod 640 /mail-tls/fullchain.pem
chmod 600 /mail-tls/privkey.pem
