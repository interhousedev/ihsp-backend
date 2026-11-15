"""Idempotent Vault bootstrap for development and production.

Enables the Transit and AppRole engines (and KV v2 at ``secret/`` when it is missing),
creates the Transit key ``emis-passwords``, writes the ``identity`` policy and the
``identity`` AppRole, and the ``telegram-bots`` policy and AppRole (bot tokens). Needs the ``hvac`` package.

Environment: VAULT_ADDR (default http://localhost:8200), VAULT_TOKEN (a root or
equivalent token; dev: dev-root), VAULT_CACERT (optional CA file).

``--print-credentials`` prints the role and secret ids of both AppRoles as ``KEY=value``
lines (IHSP_VAULT__ROLE_ID, IHSP_VAULT__SECRET_ID, IHSP_BOT_VAULT__ROLE_ID,
IHSP_BOT_VAULT__SECRET_ID). They are secrets: ``scripts/prod_init.sh`` captures the
output into the env file; never run it where stdout goes to a terminal or a CI log.
"""

import argparse
import os
import sys
from pathlib import Path

import hvac
from hvac.exceptions import InvalidPath

ROLE = "identity"
TRANSIT_KEY = "emis-passwords"
POLICY_FILE = Path(__file__).parent / "policies" / "identity.hcl"
BOT_ROLE = "telegram-bots"
BOT_POLICY_FILE = Path(__file__).parent / "policies" / "telegram-bots.hcl"
KV_MAX_VERSIONS = 2  # keep old EMIS secrets from piling up in history


def _mounted(client: hvac.Client) -> set[str]:
    return set(client.sys.list_mounted_secrets_engines()["data"])


def bootstrap(client: hvac.Client) -> None:
    """Create everything the identity process needs; safe to run repeatedly."""
    mounts = _mounted(client)
    if "transit/" not in mounts:
        client.sys.enable_secrets_engine(backend_type="transit", path="transit")
    if "secret/" not in mounts:
        client.sys.enable_secrets_engine(
            backend_type="kv", path="secret", options={"version": "2"}
        )
    if "approle/" not in client.sys.list_auth_methods()["data"]:
        client.sys.enable_auth_method(method_type="approle")
    try:
        client.secrets.transit.read_key(name=TRANSIT_KEY)
    except InvalidPath:
        client.secrets.transit.create_key(name=TRANSIT_KEY, key_type="aes256-gcm96")
    client.secrets.kv.v2.configure(max_versions=KV_MAX_VERSIONS, mount_point="secret")
    client.sys.create_or_update_policy(
        name=ROLE, policy=POLICY_FILE.read_text(encoding="utf-8")
    )
    client.auth.approle.create_or_update_approle(
        role_name=ROLE, token_policies=[ROLE], token_ttl="1h", token_max_ttl="24h"
    )
    client.sys.create_or_update_policy(
        name=BOT_ROLE, policy=BOT_POLICY_FILE.read_text(encoding="utf-8")
    )
    client.auth.approle.create_or_update_approle(
        role_name=BOT_ROLE,
        token_policies=[BOT_ROLE],
        token_ttl="1h",
        token_max_ttl="24h",
    )


def revoke_secret_ids(client: hvac.Client, role: str) -> None:
    """Destroy every existing secret id of an AppRole (they never expire)."""
    try:
        listed = client.auth.approle.list_secret_id_accessors(role_name=role)
    except InvalidPath:
        return
    for accessor in listed["data"]["keys"]:
        client.auth.approle.destroy_secret_id_accessor(
            role_name=role, secret_id_accessor=accessor
        )


def credentials(client: hvac.Client, role: str = ROLE) -> tuple[str, str]:
    """Return (role_id, a new secret_id) of an AppRole (identity by default).

    Every earlier secret id of the role is revoked first; running services keep their
    Vault token until it expires and then log in with the new secret id.
    """
    role_id = client.auth.approle.read_role_id(role_name=role)["data"]["role_id"]
    revoke_secret_ids(client, role)
    secret_id = client.auth.approle.generate_secret_id(role_name=role)["data"][
        "secret_id"
    ]
    return role_id, secret_id


def main() -> int:
    """Run the bootstrap from the command line."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--print-credentials", action="store_true")
    args = parser.parse_args()
    client = hvac.Client(
        url=os.environ.get("VAULT_ADDR", "http://localhost:8200"),
        token=os.environ["VAULT_TOKEN"],
        verify=os.environ.get("VAULT_CACERT") or True,
    )
    bootstrap(client)
    sys.stdout.write("vault bootstrap done\n")
    if args.print_credentials:
        role_id, secret_id = credentials(client)
        bot_role_id, bot_secret_id = credentials(client, BOT_ROLE)
        sys.stdout.write(
            f"IHSP_VAULT__ROLE_ID={role_id}\n"
            f"IHSP_VAULT__SECRET_ID={secret_id}\n"
            f"IHSP_BOT_VAULT__ROLE_ID={bot_role_id}\n"
            f"IHSP_BOT_VAULT__SECRET_ID={bot_secret_id}\n"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
