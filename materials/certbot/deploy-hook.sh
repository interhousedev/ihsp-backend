#!/bin/sh
# certbot deploy hook (runs after every issue and renewal, inside the certbot container).
# The mail process is not root and cannot read certbot's private key (mode 600), so a copy
# goes to a directory that only the mail container mounts (../data/mail-tls). The host
# path ../data is mode 700, which keeps other host users away from the key.
set -eu
mkdir -p /mail-tls
cp "$RENEWED_LINEAGE/fullchain.pem" /mail-tls/fullchain.pem
cp "$RENEWED_LINEAGE/privkey.pem" /mail-tls/privkey.pem
chmod 755 /mail-tls
chmod 644 /mail-tls/fullchain.pem /mail-tls/privkey.pem
