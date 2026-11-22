"""Ports of the essay key administration: ledger, backup codec, resealer."""

import datetime as dt
from dataclasses import dataclass
from typing import Literal, Protocol
from uuid import UUID

from app.modules.admission.ports.essay_crypto import EssayKey
from app.modules.admission.ports.repositories import AuditEvent

RotationState = Literal["idle", "running", "done", "failed"]


@dataclass(frozen=True, slots=True)
class RotationProgress:
    """The last (or running) key rotation."""

    state: RotationState
    total: int
    done: int
    unreadable: int
    started_at: dt.datetime | None
    finished_at: dt.datetime | None
    requested_by: UUID | None


@dataclass(frozen=True, slots=True)
class EssayKeyLedgerState:
    """The key generation, its backup (if taken) and the rotation."""

    generation: int
    exported_at: dt.datetime | None
    exported_by: UUID | None
    rotation: RotationProgress


@dataclass(frozen=True, slots=True)
class BackupContents:
    """The opened backup file."""

    generation: int
    keys: tuple[EssayKey, ...]


@dataclass(frozen=True, slots=True)
class ResealResult:
    """One student's rotation: blobs moved to the new key and blobs left alone."""

    resealed: int
    unreadable: int


class EssayKeyLedger(Protocol):
    """The single ledger row and the backup claims (SQL)."""

    async def state(self) -> EssayKeyLedgerState:
        """The current ledger."""
        ...

    async def claim_export(
        self, generation: int, actor_id: UUID, at: dt.datetime, event: AuditEvent
    ) -> bool:
        """Record the one backup of the generation; False when already taken."""
        ...

    async def start_rotation(self, actor_id: UUID, at: dt.datetime) -> bool:
        """Mark a rotation running; False when one already runs."""
        ...

    async def set_total(self, total: int) -> None:
        """Store how many students the running rotation covers; resets progress."""
        ...

    async def advance(self, unreadable: int) -> None:
        """Count one more student done and its unreadable blobs."""
        ...

    async def finish_rotation(self, at: dt.datetime) -> None:
        """Mark the rotation done and bump the generation."""
        ...

    async def fail_rotation(self, at: dt.datetime) -> None:
        """Mark the rotation failed (a new POST resumes it)."""
        ...

    async def audit(self, event: AuditEvent) -> None:
        """Write one audit event."""
        ...


class EssayKeyBackupCodec(Protocol):
    """Encrypts the key set with a passphrase and opens it again."""

    def seal(self, keys: list[EssayKey], passphrase: str, generation: int) -> bytes:
        """The backup file (JSON); never holds a plaintext key."""
        ...

    def open(self, data: bytes, passphrase: str) -> BackupContents:
        """The keys of a backup; EssayKeysBackupInvalidError when it does not open."""
        ...


class EssayResealer(Protocol):
    """Moves one student's sealed columns from the old key to the pending key."""

    async def reseal(self, key: EssayKey) -> ResealResult:
        """In one transaction; rows already under the pending key are left as is."""
        ...
