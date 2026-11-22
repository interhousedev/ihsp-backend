"""Ports of the essay key administration: ledger, backup codec, resealer."""

import datetime as dt
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Final, Literal, Protocol
from uuid import UUID

from app.modules.admission.ports.essay_crypto import EssayKey
from app.modules.admission.ports.repositories import AuditEvent

RotationState = Literal["idle", "running", "done", "failed"]

MAX_BACKUP_KEYS: Final = 20_000
"""More students than the lyceum will ever have; caps the work of one restore."""
MAX_BACKUP_CIPHERTEXT: Final = 8 * 1024 * 1024
"""Base64 characters of a backup's sealed key list (about 250 bytes per key)."""


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
    run_id: UUID | None = None
    heartbeat_at: dt.datetime | None = None


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


class RotationFencedError(Exception):
    """This rotation run lost its lease; another run owns the rotation now."""


BackupBuilder = Callable[[int], Awaitable[tuple[bytes, AuditEvent]]]
"""Makes the backup file and its audit event for a generation."""


class EssayKeyLedger(Protocol):
    """The single ledger row and the backup claims (SQL).

    A rotation run holds a lease: its `run_id` and a heartbeat renewed with every
    step. Each run method changes the row only while the run still owns it and
    returns False (or raises `RotationFencedError`) once another run took over.
    """

    async def state(self) -> EssayKeyLedgerState:
        """The current ledger."""
        ...

    async def export(
        self, actor_id: UUID, at: dt.datetime, build: BackupBuilder
    ) -> bytes:
        """Build and claim the one backup of the generation under the ledger lock.

        Raises EssayKeysRotationRunningError unless the rotation is idle or done,
        EssayKeysBackupTakenError when the generation was backed up already. No
        rotation can start while the backup is built.
        """
        ...

    async def start_rotation(
        self, run_id: UUID, actor_id: UUID, at: dt.datetime, stale_before: dt.datetime
    ) -> bool:
        """Start run `run_id`; False while a run with a fresh heartbeat holds it.

        A heartbeat older than `stale_before` lets the new run take over.
        """
        ...

    async def heartbeat(self, run_id: UUID, at: dt.datetime) -> bool:
        """Renew the lease; False when the run lost it."""
        ...

    async def set_total(self, run_id: UUID, total: int, at: dt.datetime) -> bool:
        """Store how many students the run covers; resets progress."""
        ...

    async def advance(self, run_id: UUID, unreadable: int, at: dt.datetime) -> bool:
        """Count one more student done and its unreadable blobs."""
        ...

    async def finish_rotation(self, run_id: UUID, at: dt.datetime) -> bool:
        """Mark the run done and bump the generation (once)."""
        ...

    async def fail_rotation(self, run_id: UUID, at: dt.datetime) -> bool:
        """Mark the run failed (a new POST resumes it)."""
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

    async def reseal(self, key: EssayKey, run_id: UUID) -> ResealResult:
        """In one transaction under the owner's exclusive write lock.

        Rows already under the pending key are left as is. Raises
        `RotationFencedError` when `run_id` no longer owns the rotation.
        """
        ...
