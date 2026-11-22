"""SQL side of the essay key administration: the ledger and the per-student reseal."""

import datetime as dt
from collections.abc import Mapping
from typing import Any, Final
from uuid import UUID

from app.modules.admission.infrastructure.essay_crypto import open_blob, seal_blob
from app.modules.admission.infrastructure.orm._common import S
from app.modules.admission.infrastructure.orm.essay_keys import (
    EssayKeyExportRow,
    EssayKeyStateRow,
)
from app.modules.admission.infrastructure.orm.sealed import SEALED_COLUMNS
from app.modules.admission.infrastructure.repositories import SqlAccessRepository
from app.modules.admission.ports.essay_crypto import EssayKey
from app.modules.admission.ports.essay_keys import (
    EssayKeyLedgerState,
    ResealResult,
    RotationProgress,
    RotationState,
)
from app.modules.admission.ports.repositories import AuditEvent
from app.shared.db.base import Base

import structlog
from sqlalchemy import Table, delete, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

log = structlog.get_logger(__name__)

_ONE = EssayKeyStateRow.id == 1


class SqlEssayKeyLedger:
    """Implements `EssayKeyLedger` on `essay_key_state` and `essay_key_exports`."""

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        """Each call runs in its own short transaction."""
        self._sm = sessionmaker

    async def state(self) -> EssayKeyLedgerState:
        """Read the ledger row and the backup of its generation."""
        async with self._sm() as s:
            row = await s.scalar(select(EssayKeyStateRow).where(_ONE))
            if row is None:  # the migration inserts it; a bare test DB may not
                row = EssayKeyStateRow(
                    id=1,
                    generation=1,
                    rotation_state="idle",
                    rotation_total=0,
                    rotation_done=0,
                    rotation_unreadable=0,
                )
                s.add(row)
                await s.commit()
            export = await s.get(EssayKeyExportRow, row.generation)
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
                ),
            )

    async def claim_export(
        self, generation: int, actor_id: UUID, at: dt.datetime, event: AuditEvent
    ) -> bool:
        """Insert the claim (ON CONFLICT DO NOTHING) with its audit event."""
        async with self._sm() as s:
            claimed = await s.scalar(
                insert(EssayKeyExportRow)
                .values(generation=generation, exported_at=at, exported_by=actor_id)
                .on_conflict_do_nothing()
                .returning(EssayKeyExportRow.generation)
            )
            if claimed is None:
                return False
            SqlAccessRepository(s).audit(event)
            await s.commit()
            return True

    async def start_rotation(self, actor_id: UUID, at: dt.datetime) -> bool:
        """Switch to running unless it already runs."""
        await self.state()  # makes sure the row exists
        async with self._sm() as s:
            started = await s.scalar(
                update(EssayKeyStateRow)
                .where(_ONE, EssayKeyStateRow.rotation_state != "running")
                .values(
                    rotation_state="running",
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

    async def _set(self, **values: object) -> None:
        async with self._sm() as s:
            await s.execute(update(EssayKeyStateRow).where(_ONE).values(**values))
            await s.commit()

    async def set_total(self, total: int) -> None:
        """Reset the counters for a (re)started run."""
        await self._set(rotation_total=total, rotation_done=0, rotation_unreadable=0)

    async def advance(self, unreadable: int) -> None:
        """One student more."""
        await self._set(
            rotation_done=EssayKeyStateRow.rotation_done + 1,
            rotation_unreadable=EssayKeyStateRow.rotation_unreadable + unreadable,
        )

    async def finish_rotation(self, at: dt.datetime) -> None:
        """Done; the next generation may be backed up again."""
        await self._set(
            rotation_state="done",
            rotation_finished_at=at,
            generation=EssayKeyStateRow.generation + 1,
        )

    async def fail_rotation(self, at: dt.datetime) -> None:
        """Failed; the generation stays."""
        await self._set(rotation_state="failed", rotation_finished_at=at)

    async def audit(self, event: AuditEvent) -> None:
        """Write the event in its own transaction."""
        async with self._sm() as s:
            SqlAccessRepository(s).audit(event)
            await s.commit()


def _table(name: str) -> Table:
    return Base.metadata.tables[f"{S}.{name}"]


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

    async def reseal(self, key: EssayKey) -> ResealResult:
        """Lock the student's rows, move every blob to the pending key, drop caches.

        A blob that opens under the pending key is already moved (a resumed run); one
        that opens under neither key is left untouched and counted.
        """
        if key.pending is None:
            return ResealResult(resealed=0, unreadable=0)
        owner = key.owner_id
        resealed = unreadable = 0
        essays = _table("essays")
        async with self._sm() as s:
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


__all__ = ["UNREADABLE", "SqlEssayKeyLedger", "SqlEssayResealer", "move_blob"]
