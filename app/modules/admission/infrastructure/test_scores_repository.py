"""SQL repository of the tests & certificates slice."""

from decimal import Decimal
from typing import Any
from uuid import UUID

from app.modules.admission.domain.test_scores import (
    ScoreEntry,
    ScoreTest,
    SectionDef,
    from_json,
    to_json,
)
from app.modules.admission.infrastructure.orm.test_scores import (
    ScoreEntryRow,
    ScoreTestRow,
)

from sqlalchemy import delete, exists, select
from sqlalchemy.ext.asyncio import AsyncSession


def section_payload(s: SectionDef) -> dict[str, Any]:
    """JSON form of a section definition."""
    return {
        "key": s.key,
        "names": s.names,
        "min": to_json(s.min),
        "max": to_json(s.max),
        "step": to_json(s.step),
        "choices": list(s.choices),
    }


def section_from(p: dict[str, Any]) -> SectionDef:
    """Parse a stored section definition."""
    return SectionDef(
        key=p["key"],
        names=dict(p["names"]),
        min=Decimal(str(p["min"])),
        max=Decimal(str(p["max"])),
        step=Decimal(str(p["step"])),
        choices=tuple(p.get("choices") or ()),
    )


def _test(r: ScoreTestRow) -> ScoreTest:
    return ScoreTest(
        id=r.id,
        key=r.key,
        names=dict(r.names),
        sections=tuple(section_from(s) for s in r.sections),
        total=section_from(r.total) if r.total else None,
        total_mode=r.total_mode,  # type: ignore[arg-type]
        superscore=r.superscore,
        needs_label=r.needs_label,
        needs_level=r.needs_level,
        position=r.position,
        active=r.active,
    )


def _values(t: ScoreTest) -> dict[str, Any]:
    return {
        "key": t.key,
        "names": t.names,
        "sections": [section_payload(s) for s in t.sections],
        "total": section_payload(t.total) if t.total else None,
        "total_mode": t.total_mode,
        "superscore": t.superscore,
        "needs_label": t.needs_label,
        "needs_level": t.needs_level,
        "position": t.position,
        "active": t.active,
    }


def _entry(r: ScoreEntryRow) -> ScoreEntry:
    sections = {k: from_json(v) for k, v in r.sections.items()}
    return ScoreEntry(
        id=r.id,
        student_id=r.student_id,
        test_id=r.test_id,
        status=r.status,  # type: ignore[arg-type]
        test_date=r.test_date,
        registration_deadline=r.registration_deadline,
        label=r.label,
        level=r.level,
        sections={k: v for k, v in sections.items() if v is not None},
        total=from_json(r.total),
        certificate_document_id=r.certificate_document_id,
        verification_url=r.verification_url,
        send_note=r.send_note,
        is_official=r.is_official,
        verified_by=r.verified_by,
        verified_at=r.verified_at,
        created_at=r.created_at,
        updated_at=r.updated_at,
    )


def _entry_values(e: ScoreEntry) -> dict[str, Any]:
    return {
        "student_id": e.student_id,
        "test_id": e.test_id,
        "status": e.status,
        "test_date": e.test_date,
        "registration_deadline": e.registration_deadline,
        "label": e.label,
        "level": e.level,
        "sections": {k: to_json(v) for k, v in e.sections.items()},
        "total": to_json(e.total),
        "certificate_document_id": e.certificate_document_id,
        "verification_url": e.verification_url,
        "send_note": e.send_note,
        "is_official": e.is_official,
        "verified_by": e.verified_by,
        "verified_at": e.verified_at,
    }


class SqlScoreRepository:
    """Catalog and entries over one session."""

    def __init__(self, session: AsyncSession) -> None:
        """Keep the session."""
        self._s = session

    async def catalog(self, *, include_inactive: bool) -> list[ScoreTest]:
        """Tests ordered by position and key."""
        q = select(ScoreTestRow).order_by(ScoreTestRow.position, ScoreTestRow.key)
        if not include_inactive:
            q = q.where(ScoreTestRow.active.is_(True))
        return [_test(r) for r in (await self._s.scalars(q)).all()]

    async def get_test(self, test_id: UUID) -> ScoreTest | None:
        """One test."""
        row = await self._s.get(ScoreTestRow, test_id)
        return _test(row) if row else None

    async def key_taken(self, key: str, *, except_id: UUID | None) -> bool:
        """Return whether another test uses the key."""
        q = select(ScoreTestRow.id).where(ScoreTestRow.key == key)
        if except_id:
            q = q.where(ScoreTestRow.id != except_id)
        return (await self._s.scalar(q)) is not None

    async def save_test(self, test: ScoreTest) -> ScoreTest:
        """Insert or update a test."""
        row = await self._s.get(ScoreTestRow, test.id)
        if row is None:
            row = ScoreTestRow(id=test.id)
            self._s.add(row)
        for k, v in _values(test).items():
            setattr(row, k, v)
        await self._s.flush()
        await self._s.refresh(row)
        return _test(row)

    async def delete_test(self, test_id: UUID) -> None:
        """Delete a test."""
        await self._s.execute(delete(ScoreTestRow).where(ScoreTestRow.id == test_id))

    async def test_in_use(self, test_id: UUID) -> bool:
        """Return whether an entry refers to the test."""
        q = select(exists().where(ScoreEntryRow.test_id == test_id))
        return bool(await self._s.scalar(q))

    async def entries(self, student_id: UUID) -> list[ScoreEntry]:
        """A student's entries, newest first."""
        q = (
            select(ScoreEntryRow)
            .where(ScoreEntryRow.student_id == student_id)
            .order_by(ScoreEntryRow.created_at.desc(), ScoreEntryRow.id.desc())
        )
        return [_entry(r) for r in (await self._s.scalars(q)).all()]

    async def get_entry(self, entry_id: UUID) -> ScoreEntry | None:
        """One entry."""
        row = await self._s.get(ScoreEntryRow, entry_id)
        return _entry(row) if row else None

    async def save_entry(self, entry: ScoreEntry) -> ScoreEntry:
        """Insert or update an entry."""
        row = await self._s.get(ScoreEntryRow, entry.id)
        if row is None:
            row = ScoreEntryRow(id=entry.id)
            self._s.add(row)
        for k, v in _entry_values(entry).items():
            setattr(row, k, v)
        await self._s.flush()
        await self._s.refresh(row)
        return _entry(row)

    async def delete_entry(self, entry_id: UUID) -> None:
        """Remove an entry."""
        await self._s.execute(delete(ScoreEntryRow).where(ScoreEntryRow.id == entry_id))
