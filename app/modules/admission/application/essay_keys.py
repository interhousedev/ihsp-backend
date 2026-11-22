"""Administration of the per-student essay keys: status, backup, restore, rotation.

Backup: one download per key generation; the file holds every key sealed with a
passphrase (scrypt + AES-256-GCM), never a plaintext key. Rotation gives every
student a new key in three steps that are each safe to repeat:

1. every key gets a pending key (new text is sealed with it at once);
2. after the key cache TTL, so every process sees the pending key, each student's
   sealed columns move to it in one transaction; unreadable blobs stay as they are;
3. the pending key replaces the old one; at the end the generation is bumped.

Keyed digests change with the key: cached idea fits are dropped, stored reviews
show as stale and are recomputed on demand.
"""

import datetime as dt
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Final
from uuid import UUID

from app.modules.admission.domain.errors import (
    AdmissionForbiddenError,
    EssayKeysBackupTakenError,
    EssayKeysRotationRunningError,
)
from app.modules.admission.ports.essay_crypto import EssayKey, EssayKeyStore
from app.modules.admission.ports.essay_keys import (
    EssayKeyBackupCodec,
    EssayKeyLedger,
    EssayKeyLedgerState,
    EssayResealer,
)
from app.modules.admission.ports.repositories import AuditEvent
from app.shared.actor import Actor, Role
from app.shared.clock import Clock
from app.shared.tasks import TaskKicker

import structlog

log = structlog.get_logger(__name__)

ROTATE_TASK: Final = "admission.essay_keys_rotate"
STALE_AFTER: Final = dt.timedelta(minutes=30)
"""A running rotation without progress this long may be restarted."""


@dataclass(frozen=True, slots=True)
class EssayKeysStatus:
    """What the admin page shows."""

    students_with_keys: int
    ledger: EssayKeyLedgerState


@dataclass(frozen=True, slots=True)
class BackupFile:
    """The download."""

    filename: str
    content: bytes


@dataclass(frozen=True, slots=True)
class RestoreReport:
    """What a restore did; `conflicts` are students whose stored key differs."""

    restored: int
    skipped: int
    conflicts: list[UUID]


def _admin(actor: Actor) -> None:
    if not actor.has(Role.ADMIN):
        raise AdmissionForbiddenError()


class EssayKeyAdmin:
    """The use cases of `/v1/admin/essay-keys`."""

    def __init__(
        self,
        store: EssayKeyStore,
        ledger: EssayKeyLedger,
        codec: EssayKeyBackupCodec,
        resealer: EssayResealer,
        kicker: TaskKicker,
        clock: Clock,
        *,
        settle: Callable[[], Awaitable[None]],
    ) -> None:
        """`settle` waits until every process's key cache has expired."""
        self._store = store
        self._ledger = ledger
        self._codec = codec
        self._resealer = resealer
        self._kicker = kicker
        self._clock = clock
        self._settle = settle

    async def status(self, actor: Actor) -> EssayKeysStatus:
        """Key count, generation, backup and rotation progress."""
        _admin(actor)
        owners = await self._store.owners()
        return EssayKeysStatus(len(owners), await self._ledger.state())

    async def backup(self, actor: Actor, passphrase: str) -> BackupFile:
        """The one backup of the current generation; 409 when it was taken."""
        _admin(actor)
        state = await self._ledger.state()
        if state.rotation.state == "running":
            raise EssayKeysRotationRunningError()
        if state.exported_at is not None:
            raise EssayKeysBackupTakenError()
        keys: list[EssayKey] = []
        for owner in await self._store.owners():
            key = await self._store.get(owner)
            if key is not None:
                keys.append(key)
        content = self._codec.seal(keys, passphrase, state.generation)
        now = self._clock.now()
        event = AuditEvent(
            action="essay_keys.backup",
            actor_id=actor.user_id,
            student_id=None,
            meta={"generation": state.generation, "count": len(keys)},
        )
        if not await self._ledger.claim_export(
            state.generation, actor.user_id, now, event
        ):
            raise EssayKeysBackupTakenError()
        name = f"essay-keys-g{state.generation}-{now:%Y%m%d-%H%M%S}.json"
        return BackupFile(filename=name, content=content)

    async def restore(
        self, actor: Actor, data: bytes, passphrase: str
    ) -> RestoreReport:
        """Write only the keys missing from the store; never overwrite."""
        _admin(actor)
        contents = self._codec.open(data, passphrase)
        restored = skipped = 0
        conflicts: list[UUID] = []
        for key in contents.keys:
            outcome = await self._store.restore(key)
            if outcome == "restored":
                restored += 1
            elif outcome == "same":
                skipped += 1
            else:
                conflicts.append(key.owner_id)
        await self._ledger.audit(
            AuditEvent(
                action="essay_keys.restore",
                actor_id=actor.user_id,
                student_id=None,
                meta={
                    "generation": contents.generation,
                    "restored": restored,
                    "skipped": skipped,
                    "conflicts": len(conflicts),
                },
            )
        )
        return RestoreReport(restored, skipped, conflicts)

    async def rotate(self, actor: Actor) -> EssayKeyLedgerState:
        """Start (or resume a stalled or failed) rotation in the worker."""
        _admin(actor)
        now = self._clock.now()
        if not await self._ledger.start_rotation(actor.user_id, now):
            state = await self._ledger.state()
            started = state.rotation.started_at
            if started is not None and now - started < STALE_AFTER:
                raise EssayKeysRotationRunningError()
            log.warning("essay_rotation_resumed")
        await self._ledger.audit(
            AuditEvent(
                action="essay_keys.rotate",
                actor_id=actor.user_id,
                student_id=None,
                meta={},
            )
        )
        await self._kicker.kick(ROTATE_TASK)
        return await self._ledger.state()

    async def run_rotation(self) -> None:
        """The worker job; every step can be repeated after a crash."""
        state = await self._ledger.state()
        if state.rotation.state != "running":
            return
        try:
            owners = await self._store.owners()
            await self._ledger.set_total(len(owners))
            for owner in owners:
                await self._store.begin_rotation(owner)
            await self._settle()
            for owner in owners:
                key = await self._store.get(owner)
                unreadable = 0
                if key is not None and key.pending is not None:
                    unreadable = (await self._resealer.reseal(key)).unreadable
                    await self._store.finish_rotation(owner)
                await self._ledger.advance(unreadable)
        except Exception:
            log.exception("essay_rotation_failed")
            await self._ledger.fail_rotation(self._clock.now())
            raise
        await self._ledger.finish_rotation(self._clock.now())
        log.info("essay_rotation_done", students=len(owners))


__all__ = ["ROTATE_TASK", "EssayKeyAdmin"]
