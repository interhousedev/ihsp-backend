"""Administration of the per-student essay keys: status, backup, restore, rotation.

Backup: one download per key generation, only between rotations; the file holds
every key sealed with a passphrase (scrypt + AES-256-GCM), never a plaintext key.

Rotation gives every student a new key. One run holds a lease (`run_id` plus a
heartbeat renewed with every step); a second run may take over only when the
heartbeat is older than `STALE_AFTER`, and every step of the old run is then
refused (fenced) by the ledger. Each step is safe to repeat:

1. every key gets a pending key; writers that seal during the rotation read their
   key from the store, so new text is sealed with the pending key at once;
2. after the key cache TTL each student's sealed columns move to the pending key in
   one transaction that waits for that student's open writers (advisory lock);
3. exactly that pending key replaces the old one; at the end the generation is
   bumped once.

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
    EssayKeysRotationRunningError,
)
from app.modules.admission.ports.essay_crypto import EssayKey, EssayKeyStore
from app.modules.admission.ports.essay_keys import (
    BackupContents,
    EssayKeyBackupCodec,
    EssayKeyLedger,
    EssayKeyLedgerState,
    EssayResealer,
    RotationFencedError,
)
from app.modules.admission.ports.repositories import AuditEvent
from app.shared.actor import Actor, Role
from app.shared.clock import Clock
from app.shared.ids import new_id
from app.shared.tasks import TaskKicker

import anyio
import structlog

log = structlog.get_logger(__name__)

ROTATE_TASK: Final = "admission.essay_keys_rotate"
STALE_AFTER: Final = dt.timedelta(minutes=10)
"""A running rotation whose heartbeat is this old may be taken over."""

_SCRYPT = anyio.Semaphore(1)
"""One scrypt at a time per process: a backup or restore costs 32 MiB and a CPU."""


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


class _Fenced(Exception):
    """The run lost its lease; stop without touching the ledger."""


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
        """The one backup of the current generation; 409 when taken or rotating."""
        _admin(actor)
        now = self._clock.now()
        generations: list[int] = []

        async def build(generation: int) -> tuple[bytes, AuditEvent]:
            generations.append(generation)
            keys: list[EssayKey] = []
            for owner in await self._store.owners():
                key = await self._store.get(owner)
                if key is not None:
                    keys.append(key)
            async with _SCRYPT:
                content = await anyio.to_thread.run_sync(
                    self._codec.seal, keys, passphrase, generation
                )
            event = AuditEvent(
                action="essay_keys.backup",
                actor_id=actor.user_id,
                student_id=None,
                meta={"generation": generation, "count": len(keys)},
            )
            return content, event

        content = await self._ledger.export(actor.user_id, now, build)
        name = f"essay-keys-g{generations[0]}-{now:%Y%m%d-%H%M%S}.json"
        return BackupFile(filename=name, content=content)

    async def restore(
        self, actor: Actor, data: bytes, passphrase: str
    ) -> RestoreReport:
        """Write only the keys missing from the store; never overwrite."""
        _admin(actor)
        async with _SCRYPT:
            contents: BackupContents = await anyio.to_thread.run_sync(
                self._codec.open, data, passphrase
            )
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
        """Start a rotation, or take over one whose heartbeat went stale."""
        _admin(actor)
        before = await self._ledger.state()
        now = self._clock.now()
        run_id = new_id()
        if not await self._ledger.start_rotation(
            run_id, actor.user_id, now, now - STALE_AFTER
        ):
            raise EssayKeysRotationRunningError()
        if before.rotation.state == "running":
            log.warning("essay_rotation_resumed", run_id=str(run_id))
        await self._ledger.audit(
            AuditEvent(
                action="essay_keys.rotate",
                actor_id=actor.user_id,
                student_id=None,
                meta={"run_id": str(run_id)},
            )
        )
        await self._kicker.kick(ROTATE_TASK, run_id=str(run_id))
        return await self._ledger.state()

    async def _step(self, ok: Awaitable[bool]) -> None:
        if not await ok:
            raise _Fenced()

    async def _rotate_owner(self, run_id: UUID, owner: UUID) -> None:
        key = await self._store.get(owner)
        unreadable = 0
        if key is not None and key.pending is not None:
            unreadable = (await self._resealer.reseal(key, run_id)).unreadable
            await self._step(self._ledger.heartbeat(run_id, self._clock.now()))
            if not await self._store.finish_rotation(owner, key.pending):
                # Another run replaced the pending key: its own reseal moves
                # this student; this run must not promote.
                raise _Fenced()
        await self._step(self._ledger.advance(run_id, unreadable, self._clock.now()))

    async def run_rotation(self, run_id: UUID) -> None:
        """The worker job of one run; stops quietly once another run took over."""
        state = await self._ledger.state()
        if state.rotation.state != "running" or state.rotation.run_id != run_id:
            return
        clock = self._clock
        try:
            owners = await self._store.owners()
            await self._step(self._ledger.set_total(run_id, len(owners), clock.now()))
            for owner in owners:
                await self._store.begin_rotation(owner)
                await self._step(self._ledger.heartbeat(run_id, clock.now()))
            await self._settle()
            await self._step(self._ledger.heartbeat(run_id, clock.now()))
            for owner in owners:
                await self._rotate_owner(run_id, owner)
            await self._step(self._ledger.finish_rotation(run_id, clock.now()))
        except (_Fenced, RotationFencedError):
            log.warning("essay_rotation_fenced", run_id=str(run_id))
            return
        except Exception:
            log.exception("essay_rotation_failed", run_id=str(run_id))
            await self._ledger.fail_rotation(run_id, clock.now())
            raise
        log.info("essay_rotation_done", run_id=str(run_id), students=len(owners))


__all__ = ["ROTATE_TASK", "STALE_AFTER", "EssayKeyAdmin"]
