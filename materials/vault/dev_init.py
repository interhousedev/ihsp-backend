"""Development Vault bootstrap: init once, unseal on every start, then setup.py.

Keeps the single unseal key and the root token in ``$VAULT_DEV_KEYS_FILE`` (default
/keys/vault-init.json, git-ignored). Ensures KV v2 at ``secret/`` and a token with the
fixed id ``dev-root`` (policy root), so ``IHSP_ESSAY_VAULT__TOKEN=dev-root`` keeps working.
"""

import json
import os
import sys
from pathlib import Path

import hvac
from hvac.exceptions import InvalidPath
from setup import bootstrap

DEV_TOKEN = "dev-root"
KEYS_FILE = Path(os.environ.get("VAULT_DEV_KEYS_FILE", "/keys/vault-init.json"))


def main() -> int:
    """Initialise, unseal and bootstrap the development Vault."""
    client = hvac.Client(url=os.environ.get("VAULT_ADDR", "http://vault:8200"))
    if not client.sys.is_initialized():
        keys = client.sys.initialize(secret_shares=1, secret_threshold=1)
        KEYS_FILE.write_text(
            json.dumps(
                {"unseal_key": keys["keys"][0], "root_token": keys["root_token"]}
            ),
            encoding="utf-8",
        )
        KEYS_FILE.chmod(0o600)
    if not KEYS_FILE.exists():
        sys.stderr.write(
            f"Vault is initialised but {KEYS_FILE} is missing: "
            "remove the vault_data volume (docker compose down -v) and retry\n"
        )
        return 1
    stored = json.loads(KEYS_FILE.read_text(encoding="utf-8"))
    if client.sys.is_sealed():
        client.sys.submit_unseal_key(stored["unseal_key"])
    client.token = stored["root_token"]
    mounts = set(client.sys.list_mounted_secrets_engines()["data"])
    if "secret/" not in mounts:
        client.sys.enable_secrets_engine(
            backend_type="kv", path="secret", options={"version": "2"}
        )
    try:
        client.lookup_token(DEV_TOKEN)
    except (InvalidPath, hvac.exceptions.Forbidden):
        client.adapter.post(
            "/v1/auth/token/create",
            json={"id": DEV_TOKEN, "policies": ["root"], "no_parent": True},
        )
    client.token = DEV_TOKEN
    bootstrap(client)
    sys.stdout.write("dev vault ready\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
