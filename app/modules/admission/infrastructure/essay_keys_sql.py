"""SQL side of the essay key administration: ledger, per-student reseal, write fence.

The write fence keeps old-key ciphertext from landing after a student was resealed.
Every transaction that seals essay text takes the owner's advisory lock in shared
mode (`FencedEssayCipher`), the reseal takes it in exclusive mode. While a rotation
runs, a writer reads its key from Vault (not the cache) after taking the lock, so it
seals with the pending key once that exists. A writer that sealed with the old key
holds the shared lock until it commits; the reseal waits for it and moves its blobs.
After the reseal no transaction can write old-key text for that student, and the
pending key can be promoted.
"""

import datetime as dt
import hashlib
from collections.abc import Mapping
from typing import Any, Final
from uuid import UUID

from app.modules.admission.domain.errors import (
    EssayKeysBackupTakenError,
    EssayKeysRotationRunningError,
)
from app.modules.admission.infrastructure.essay_crypto import (
    AesGcmEssayCipher,
    open_blob,
    seal_blob,
)
from app.modules.admission.infrastructure.orm._common import SCHEMA
from app.modules.admission.infrastructure.orm.essay_keys import (
    EssayKeyExportRow,
    EssayKeyStateRow,
)
from app.modules.admission.infrastructure.orm.sealed import SEALED_COLUMNS
from app.modules.admission.infrastructure.repositories import SqlAccessRepository
from app.modules.admission.ports.essay_crypto import EssayCipher, EssayKey
from app.modules.admission.ports.essay_keys import (
    BackupBuilder,
    EssayKeyLedgerState,
    ResealResult,
    RotationFencedError,
    RotationProgress,
    RotationState,
)
from app.modules.admission.ports.repositories import AuditEvent
from app.shared.db.base import Base

import structlog
from sqlalchemy import ColumnElement, Table, delete, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

log = structlog.get_logger(__name__)

_ONE = EssayKeyStateRow.id == 1
_BACKUP_STATES: Final = ("idle", "done")
"""A backup is a consistent snapshot only between rotations."""
_LOCK_INFO: Final = b"ihsp-essay-key-owner|"
_DEADLOCK: Final = "40P01"
_DEADLOCK_RETRIES: Final = 3


def _sqlstate(exc: DBAPIError) -> str | None:
    orig = exc.orig
    return getattr(orig, "sqlstate", None) or getattr(orig, "pgcode", None)


def owner_lock_key(owner_id: UUID) -> int:
    """The advisory lock id of one student's sealed text (signed 64-bit)."""
    digest = hashlib.sha256(_LOCK_INFO + owner_id.bytes).digest()
    return int.from_bytes(digest[:8], "big", signed=True)


def _owns(run_id: UUID) -> ColumnElement[bool]:
    return (EssayKeyStateRow.rotation_run_id == run_id) & (
        EssayKeyStateRow.rotation_state == "running"
    )


class SqlEssayKeyLedger:
    """Implements `EssayKeyLedger` on `essay_key_state` and `essay_key_exports`."""

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        """Each call runs in its own short transaction."""
        self._sm = sessionmaker

    async def _row(self, s: AsyncSession, *, lock: bool = False) -> EssayKeyStateRow:
        q = select(EssayKeyStateRow).where(_ONE)
        row = await s.scalar(q.with_for_update() if lock else q)
        if row is None:  # the migration inserts it; a bare test DB may not
            await s.execute(
                insert(EssayKeyStateRow).values(id=1).on_conflict_do_nothing()
            )
            row = await s.scalar(q.with_for_update() if lock else q)
            assert row is not None
        return row

    async def state(self) -> EssayKeyLedgerState:
        """Read the ledger row and the backup of its generation."""
        async with self._sm() as s:
            row = await self._row(s)
            export = await s.get(EssayKeyExportRow, row.generation)
            await s.commit()
            state: RotationState = row.rotation_state  # type: ignore[assignment]
            return EssayKeyLedgerState(
                generation=row.generation,
                exported_at=None if export is None else export.exported_at,
                exported_by=None if export is None else export.exported_by,
                rotation=RotationProgress(
                    state=state,
                    total=row.rotation_total,
                    done=row.rotation_done,
                    unreadable=row.rotation_unreadable,
                    started_at=row.rotation_started_at,
                    finished_at=row.rotation_finished_at,
                    requested_by=row.rotation_by,
                    run_id=row.rotation_run_id,
                    heartbeat_at=row.rotation_heartbeat_at,
                ),
            )

    async def export(
        self, actor_id: UUID, at: dt.datetime, build: BackupBuilder
    ) -> bytes:
        """Lock the ledger row, check it, build the file, claim the generation.

        The row stays locked while the keys are read, so no rotation starts during
        the snapshot (`start_rotation` waits for it).
        """
        async with self._sm() as s:
            row = await self._row(s, lock=True)
            if row.rotation_state not in _BACKUP_STATES:
                raise EssayKeysRotationRunningError()
            generation = row.generation
            if await s.get(EssayKeyExportRow, generation) is not None:
                raise EssayKeysBackupTakenError()
            content, event = await build(generation)
            claimed = await s.scalar(
                insert(EssayKeyExportRow)
                .values(generation=generation, exported_at=at, exported_by=actor_id)
                .on_conflict_do_nothing()
                .returning(EssayKeyExportRow.generation)
            )
            if claimed is None:
                raise EssayKeysBackupTakenError()
            SqlAccessRepository(s).audit(event)
            await s.commit()
            return content

    async def start_rotation(
        self, run_id: UUID, actor_id: UUID, at: dt.datetime, stale_before: dt.datetime
    ) -> bool:
        """Take the lease unless a run with a recent heartbeat holds it."""
        async with self._sm() as s:
            await self._row(s)  # makes sure the row exists
            started = await s.scalar(
                update(EssayKeyStateRow)
                .where(
                    _ONE,
                    or_(
                        EssayKeyStateRow.rotation_state != "running",
                        EssayKeyStateRow.rotation_heartbeat_at.is_(None),
                        EssayKeyStateRow.rotation_heartbeat_at < stale_before,
                    ),
                )
                .values(
                    rotation_state="running",
                    rotation_run_id=run_id,
                    rotation_heartbeat_at=at,
                    rotation_total=0,
                    rotation_done=0,
                    rotation_unreadable=0,
                    rotation_by=actor_id,
                    rotation_started_at=at,
                    rotation_finished_at=None,
                )
                .returning(EssayKeyStateRow.id)
            )
            await s.commit()
            return started is not None

    async def _fenced(self, run_id: UUID, at: dt.datetime, **values: object) -> bool:
        async with self._sm() as s:
            done = await s.scalar(
                update(EssayKeyStateRow)
                .where(_ONE, _owns(run_id))
                .values(rotation_heartbeat_at=at, **values)
                .returning(EssayKeyStateRow.id)
            )
            await s.commit()
            return done is not None

    async def heartbeat(self, run_id: UUID, at: dt.datetime) -> bool:
        """Renew the lease."""
        return await self._fenced(run_id, at)

    async def set_total(self, run_id: UUID, total: int, at: dt.datetime) -> bool:
        """Reset the counters for a (re)started run."""
        return await self._fenced(
            run_id, at, rotation_total=total, rotation_done=0, rotation_unreadable=0
        )

    async def advance(self, run_id: UUID, unreadable: int, at: dt.datetime) -> bool:
        """One student more."""
        return await self._fenced(
            run_id,
            at,
            rotation_done=EssayKeyStateRow.rotation_done + 1,
            rotation_unreadable=EssayKeyStateRow.rotation_unreadable + unreadable,
        )

    async def finish_rotation(self, run_id: UUID, at: dt.datetime) -> bool:
        """Done; the generation moves on exactly once (the run leaves 'running')."""
        return await self._fenced(
            run_id,
            at,
            rotation_state="done",
            rotation_finished_at=at,
            generation=EssayKeyStateRow.generation + 1,
        )

    async def fail_rotation(self, run_id: UUID, at: dt.datetime) -> bool:
        """Failed; the generation stays."""
        return await self._fenced(
            run_id, at, rotation_state="failed", rotation_finished_at=at
        )

    async def audit(self, event: AuditEvent) -> None:
        """Write the event in its own transaction."""
        async with self._sm() as s:
            SqlAccessRepository(s).audit(event)
            await s.commit()


def _table(name: str) -> Table:
    return Base.metadata.tables[f"{SCHEMA}.{name}"]


class Unreadable:
    """`move_blob` result for a blob that opens under neither key."""


UNREADABLE: Final = Unreadable()


def move_blob(
    key: EssayKey, record: UUID, column: str, blob: bytes
) -> bytes | Unreadable | None:
    """The blob sealed with `key.pending`; None when it already is."""
    if key.pending is None:
        raise ValueError("the key has no pending key")
    owner = key.owner_id
    try:
        if open_blob(key.pending, owner, record, column, blob) is not None:
            return None
        text = open_blob(key.secret, owner, record, column, blob)
    except ValueError:
        text = None
    if text is None:
        return UNREADABLE
    return seal_blob(key.pending, owner, record, column, text)


def _move_row(
    key: EssayKey, record: UUID, values: Mapping[Any, Any], cols: list[str]
) -> tuple[dict[str, bytes], int]:
    """New blobs of one row and how many of its blobs opened under neither key."""
    changes: dict[str, bytes] = {}
    lost = 0
    for column in cols:
        blob = values[column]
        if blob is None:
            continue
        moved = move_blob(key, record, column, bytes(blob))
        if isinstance(moved, Unreadable):
            lost += 1
        elif moved is not None:
            changes[column] = moved
    return changes, lost


class SqlEssayResealer:
    """Implements `EssayResealer` over every table of `SEALED_COLUMNS`."""

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        """One transaction per student."""
        self._sm = sessionmaker

    async def reseal(self, key: EssayKey, run_id: UUID) -> ResealResult:
        """Fence writers, check the lease, move every blob to the pending key.

        A blob that opens under the pending key is already moved (a resumed run); one
        that opens under neither key is left untouched and counted.
        """
        if key.pending is None:
            return ResealResult(resealed=0, unreadable=0)
        for attempt in range(_DEADLOCK_RETRIES):
            try:
                return await self._reseal(key, run_id)
            except DBAPIError as exc:
                # A writer that flushed rows before sealing can deadlock with the
                # fence; Postgres aborts one side and the reseal simply runs again.
                last = attempt == _DEADLOCK_RETRIES - 1
                if last or _sqlstate(exc) != _DEADLOCK:
                    raise
                log.warning("essay_rotation_deadlock", owner_id=str(key.owner_id))
        raise AssertionError("unreachable")

    async def _reseal(self, key: EssayKey, run_id: UUID) -> ResealResult:
        owner = key.owner_id
        resealed = unreadable = 0
        essays = _table("essays")
        async with self._sm() as s:
            # Exclusive: waits for every open writer of this student to commit.
            await s.execute(select(func.pg_advisory_xact_lock(owner_lock_key(owner))))
            # Shared row lock: a takeover waits until this reseal commits.
            owned = await s.scalar(
                select(EssayKeyStateRow.id)
                .where(_ONE, _owns(run_id))
                .with_for_update(read=True)
            )
            if owned is None:
                raise RotationFencedError()
            for name, columns in SEALED_COLUMNS.items():
                table = _table(name)
                cols = sorted(columns)
                q = select(table.c.id, *(table.c[c] for c in cols))
                if "student_id" in table.c:
                    q = q.where(table.c.student_id == owner)
                else:
                    q = q.join(essays, essays.c.id == table.c.essay_id).where(
                        essays.c.student_id == owner
                    )
                rows = (await s.execute(q.with_for_update(of=table))).all()
                for row in rows:
                    changes, lost = _move_row(key, row.id, row._mapping, cols)
                    unreadable += lost
                    if changes:
                        await s.execute(
                            update(table).where(table.c.id == row.id).values(**changes)
                        )
                        resealed += len(changes)
            fits = _table("idea_fits")
            await s.execute(delete(fits).where(fits.c.student_id == owner))
            await s.commit()
        if unreadable:
            log.warning(
                "essay_rotation_unreadable", owner_id=str(owner), count=unreadable
            )
        return ResealResult(resealed=resealed, unreadable=unreadable)


class FencedEssayCipher:
    """`EssayCipher` of one unit of work whose seals take the owner's write fence.

    The first seal for a student in a transaction takes the shared advisory lock
    and, while a rotation runs, reads the key from the store; later seals of the
    same transaction reuse that key.
    """

    def __init__(self, session: AsyncSession, cipher: AesGcmEssayCipher) -> None:
        """Seal under the session's fence with keys from `cipher`."""
        self._session = session
        self._cipher = cipher
        self._tx: object | None = None
        self._fenced: dict[UUID, EssayKey] = {}

    async def _write_key(self, owner_id: UUID) -> EssayKey:
        tx = self._session.get_transaction()
        if tx is None or tx is not self._tx:
            self._fenced.clear()  # a new transaction has no lock yet
        key = self._fenced.get(owner_id)
        if key is not None:
            return key
        s = self._session
        lock = func.pg_advisory_xact_lock_shared(owner_lock_key(owner_id))
        # Sealing runs while the caller builds rows whose sealed columns are still
        # empty: the fence queries must never flush them.
        with s.no_autoflush:
            await s.execute(select(lock))
            state = select(EssayKeyStateRow.rotation_state).where(_ONE)
            rotation = await s.scalar(state)
        key = await self._cipher.write_key(owner_id, fresh=rotation == "running")
        self._tx = s.get_transaction()
        self._fenced[owner_id] = key
        return key

    async def seal(
        self, owner_id: UUID, record_id: UUID, column: str, text: str
    ) -> bytes:
        """Seal under the fence with the owner's active key."""
        key = await self._write_key(owner_id)
        return seal_blob(key.active, owner_id, record_id, column, text)

    async def open(
        self, owner_id: UUID, record_id: UUID, column: str, blob: bytes
    ) -> str:
        """Open through the wrapped cipher."""
        return await self._cipher.open(owner_id, record_id, column, blob)

    async def digest(self, owner_id: UUID, purpose: str, data: str) -> str:
        """Digest through the wrapped cipher."""
        return await self._cipher.digest(owner_id, purpose, data)

    async def forget(self, owner_id: UUID) -> None:
        """Forget through the wrapped cipher."""
        await self._cipher.forget(owner_id)


def fenced_cipher(session: AsyncSession, cipher: EssayCipher) -> EssayCipher:
    """The unit of work's cipher: fenced when it hands out write keys."""
    if isinstance(cipher, AesGcmEssayCipher):
        return FencedEssayCipher(session, cipher)
    return cipher  # a test fake without a key store


__all__ = [
    "UNREADABLE",
    "FencedEssayCipher",
    "SqlEssayKeyLedger",
    "SqlEssayResealer",
    "fenced_cipher",
    "move_blob",
    "owner_lock_key",
]
