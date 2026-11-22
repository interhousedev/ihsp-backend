"""The passphrase-encrypted backup file of the essay data keys.

Format (JSON, version 1)::

    {"format": "ihsp-essay-keys-backup", "version": 1, "generation": 3,
     "created_at": "...", "count": 120,
     "kdf": {"name": "scrypt", "n": 32768, "r": 8, "p": 1, "length": 32,
             "salt": "<b64>"},
     "cipher": {"name": "AES-256-GCM", "nonce": "<b64>"},
     "ciphertext": "<b64>"}

The plaintext is ``{"keys": [{"owner_id", "dek", "pending_dek"?}]}``; the associated
data binds the format, the version and the generation, so editing them breaks the tag.
"""

import base64
import json
import os
from datetime import UTC, datetime
from typing import Any, Final
from uuid import UUID

from app.modules.admission.domain.errors import EssayKeysBackupInvalidError
from app.modules.admission.ports.essay_crypto import EssayKey
from app.modules.admission.ports.essay_keys import (
    MAX_BACKUP_CIPHERTEXT,
    MAX_BACKUP_KEYS,
    BackupContents,
)

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

FORMAT: Final = "ihsp-essay-keys-backup"
VERSION: Final = 1
SCRYPT_N: Final = 2**15
SCRYPT_R: Final = 8
SCRYPT_P: Final = 1
SALT_BYTES: Final = 16
NONCE_BYTES: Final = 12
KEY_LENGTH: Final = 32
MAX_KEYS: Final = MAX_BACKUP_KEYS
MAX_CIPHERTEXT_B64: Final = MAX_BACKUP_CIPHERTEXT
MAX_FILE_BYTES: Final = MAX_CIPHERTEXT_B64 + 4096


def _b64decode(value: object, *, exact: int | None = None, limit: int = 128) -> bytes:
    if not isinstance(value, str) or len(value) > limit:
        raise ValueError("bad base64 field")
    raw = base64.b64decode(value, validate=True)
    if exact is not None and len(raw) != exact:
        raise ValueError("bad field length")
    return raw


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def _aad(generation: int) -> bytes:
    return f"{FORMAT}|{VERSION}|{generation}".encode()


def _derive(passphrase: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    return Scrypt(salt=salt, length=32, n=n, r=r, p=p).derive(passphrase.encode())


class ScryptAesGcmBackupCodec:
    """Implements `EssayKeyBackupCodec` with scrypt and AES-256-GCM."""

    def __init__(self, n: int = SCRYPT_N) -> None:
        """`n` is the scrypt cost (tests may lower it)."""
        self._n = n

    def seal(self, keys: list[EssayKey], passphrase: str, generation: int) -> bytes:
        """The backup file as UTF-8 JSON."""
        entries: list[dict[str, str]] = []
        for key in keys:
            entry = {"owner_id": str(key.owner_id), "dek": _b64(key.secret)}
            if key.pending is not None:
                entry["pending_dek"] = _b64(key.pending)
            entries.append(entry)
        salt, nonce = os.urandom(SALT_BYTES), os.urandom(NONCE_BYTES)
        secret = _derive(passphrase, salt, self._n, SCRYPT_R, SCRYPT_P)
        plain = json.dumps({"keys": entries}).encode()
        sealed = AESGCM(secret).encrypt(nonce, plain, _aad(generation))
        doc = {
            "format": FORMAT,
            "version": VERSION,
            "generation": generation,
            "created_at": datetime.now(UTC).isoformat(),
            "count": len(entries),
            "kdf": {
                "name": "scrypt",
                "n": self._n,
                "r": SCRYPT_R,
                "p": SCRYPT_P,
                "length": 32,
                "salt": _b64(salt),
            },
            "cipher": {"name": "AES-256-GCM", "nonce": _b64(nonce)},
            "ciphertext": _b64(sealed),
        }
        return json.dumps(doc, indent=2).encode()

    def _header(self, data: bytes) -> tuple[int, bytes, bytes, bytes]:
        """Generation, salt, nonce, ciphertext; ValueError unless exactly format v1."""
        if len(data) > MAX_FILE_BYTES:
            raise ValueError("backup too large")
        doc: dict[str, Any] = json.loads(data)
        if doc["format"] != FORMAT or doc["version"] != VERSION:
            raise ValueError("not an essay key backup")
        kdf, cipher = doc["kdf"], doc["cipher"]
        params = (kdf["name"], kdf["n"], kdf["r"], kdf["p"], kdf["length"])
        if params != ("scrypt", self._n, SCRYPT_R, SCRYPT_P, KEY_LENGTH):
            raise ValueError("unsupported kdf")
        if cipher["name"] != "AES-256-GCM":
            raise ValueError("unsupported cipher")
        count, generation = doc["count"], doc["generation"]
        if not isinstance(count, int) or not 0 <= count <= MAX_KEYS:
            raise ValueError("too many keys")
        if not isinstance(generation, int) or generation < 1:
            raise ValueError("bad generation")
        return (
            generation,
            _b64decode(kdf["salt"], exact=SALT_BYTES),
            _b64decode(cipher["nonce"], exact=NONCE_BYTES),
            _b64decode(doc["ciphertext"], limit=MAX_CIPHERTEXT_B64),
        )

    def open(self, data: bytes, passphrase: str) -> BackupContents:
        """The keys; EssayKeysBackupInvalidError on damage or a wrong passphrase.

        Only the exact parameters this codec writes are accepted, and every size is
        checked before scrypt runs: a crafted file cannot ask for more work or memory
        than a real backup.
        """
        try:
            generation, salt, nonce, sealed = self._header(data)
            secret = _derive(passphrase, salt, self._n, SCRYPT_R, SCRYPT_P)
            plain = AESGCM(secret).decrypt(nonce, sealed, _aad(generation))
            entries = json.loads(plain)["keys"]
            if len(entries) > MAX_KEYS:
                raise ValueError("too many keys")
            keys = tuple(
                EssayKey(
                    UUID(e["owner_id"]),
                    base64.b64decode(e["dek"]),
                    base64.b64decode(e["pending_dek"]) if "pending_dek" in e else None,
                )
                for e in entries
            )
        except (
            InvalidTag,
            ValueError,
            KeyError,
            TypeError,
        ) as exc:
            raise EssayKeysBackupInvalidError(
                support_details=f"essay key backup: {type(exc).__name__}"
            ) from exc
        return BackupContents(generation=generation, keys=keys)


__all__ = ["ScryptAesGcmBackupCodec"]
