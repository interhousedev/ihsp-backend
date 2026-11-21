"""SQL adapters of the essay flow: prompt catalog, practice, gallery and slots.

Practice `body` and `evaluation` are sealed per student like every essay text.
"""

import datetime as dt
import json
from collections.abc import Sequence
from typing import Any
from uuid import UUID

from app.modules.admission.domain.essay_flow import (
    GalleryEntry,
    GroupLabel,
    PracticeEntry,
    PracticeEvaluation,
    PracticeScore,
    PromptRef,
    SlotAssignment,
    StoredIdeaFit,
    prompt_key,
)
from app.modules.admission.infrastructure.essays_repository import (
    _target_json,
    _targets,
)
from app.modules.admission.infrastructure.orm.catalog import InstitutionRow
from app.modules.admission.infrastructure.orm.essay_flow import (
    EssayGalleryRow,
    EssayPracticeRow,
    EssaySlotRow,
    IdeaFitRow,
    PromptGroupLabelRow,
)
from app.modules.admission.infrastructure.orm.sealed import to_json
from app.modules.admission.infrastructure.orm.supp_prompts import SuppPromptRow
from app.modules.admission.ports.essay_crypto import EssayCipher
from app.shared.ids import new_id

from sqlalchemy import and_, delete
from sqlalchemy import func as sa_func
from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession


def _ref(row: SuppPromptRow, name: str) -> PromptRef:
    return PromptRef(
        key=prompt_key(row.institution_id, row.position),
        institution_id=row.institution_id,
        institution_name=name,
        position=row.position,
        prompt=row.prompt,
        word_limit=row.word_limit,
        limit_unit=row.limit_unit,
        required=row.required,
    )


class SqlPromptCatalog:
    """Prompts in `admission.supp_prompts`; only the newest cycle of an institution."""

    def __init__(self, session: AsyncSession) -> None:
        """Keep the session."""
        self._s = session

    async def _latest(
        self, institution_id: UUID | None
    ) -> list[tuple[SuppPromptRow, str]]:
        q = (
            select(SuppPromptRow, InstitutionRow.name)
            .join(InstitutionRow, InstitutionRow.id == SuppPromptRow.institution_id)
            .where(InstitutionRow.status != "archived")
            .order_by(
                InstitutionRow.name,
                SuppPromptRow.institution_id,
                SuppPromptRow.cycle.desc(),
                SuppPromptRow.position,
            )
        )
        if institution_id is not None:
            q = q.where(SuppPromptRow.institution_id == institution_id)
        out: list[tuple[SuppPromptRow, str]] = []
        cycle: dict[UUID, str] = {}
        for row, name in (await self._s.execute(q)).all():
            if not row.prompt.strip():
                continue
            if cycle.setdefault(row.institution_id, row.cycle) == row.cycle:
                out.append((row, name))
        return out

    async def all(self) -> list[PromptRef]:
        """The prompts of every non-archived institution, by name and position."""
        return [_ref(r, n) for r, n in await self._latest(None)]

    async def for_institution(self, institution_id: UUID) -> list[PromptRef]:
        """The prompts of one institution's latest cycle, by position."""
        return [_ref(r, n) for r, n in await self._latest(institution_id)]


def _evaluation_json(value: PracticeEvaluation) -> dict[str, Any]:
    return {
        "summary": value.summary,
        "scores": [
            {"key": s.key, "score": s.score, "comment": s.comment} for s in value.scores
        ],
        "praise": list(value.praise),
        "try_next": list(value.try_next),
        "idea_seeds": list(value.idea_seeds),
        "locale": value.locale,
    }


def _evaluation(raw: dict[str, Any]) -> PracticeEvaluation:
    return PracticeEvaluation(
        summary=str(raw["summary"]),
        scores=tuple(
            PracticeScore(str(s["key"]), int(s["score"]), str(s["comment"]))
            for s in raw["scores"]
        ),
        praise=tuple(str(t) for t in raw["praise"]),
        try_next=tuple(str(t) for t in raw["try_next"]),
        idea_seeds=tuple(str(t) for t in raw["idea_seeds"]),
        locale=str(raw.get("locale") or ""),
    )


class SqlPracticeRepository:
    """Practice entries in `admission.essay_practice`."""

    def __init__(self, session: AsyncSession, cipher: EssayCipher) -> None:
        """Keep the session and the cipher."""
        self._s = session
        self._cipher = cipher

    async def _view(self, row: EssayPracticeRow) -> PracticeEntry:
        o, rid = row.student_id, row.id
        evaluation = None
        if row.evaluation is not None:
            text = await self._cipher.open(o, rid, "evaluation", row.evaluation)
            evaluation = _evaluation(json.loads(text))
        return PracticeEntry(
            id=row.id,
            student_id=row.student_id,
            day=row.day,
            theme=row.theme,
            body=await self._cipher.open(o, rid, "body", row.body),
            evaluation=evaluation,
            model=row.model,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    async def _row(self, student_id: UUID, day: dt.date) -> EssayPracticeRow | None:
        q = select(EssayPracticeRow).where(
            EssayPracticeRow.student_id == student_id, EssayPracticeRow.day == day
        )
        return (await self._s.scalars(q)).first()

    async def get(self, student_id: UUID, day: dt.date) -> PracticeEntry | None:
        """The entry of the day, or None."""
        row = await self._row(student_id, day)
        return None if row is None else await self._view(row)

    async def save(self, entry: PracticeEntry) -> PracticeEntry:
        """Insert the entry or replace the one of the same student and day."""
        row = await self._row(entry.student_id, entry.day)
        if row is None:
            row = EssayPracticeRow(
                id=entry.id, student_id=entry.student_id, day=entry.day
            )
            self._s.add(row)
        o, rid = row.student_id, row.id
        row.theme = entry.theme
        row.body = await self._cipher.seal(o, rid, "body", entry.body)
        row.evaluation = (
            None
            if entry.evaluation is None
            else await self._cipher.seal(
                o, rid, "evaluation", to_json(_evaluation_json(entry.evaluation))
            )
        )
        row.model = entry.model
        await self._s.flush()
        await self._s.refresh(row)
        return await self._view(row)

    async def recent(self, student_id: UUID, limit: int) -> list[PracticeEntry]:
        """The newest entries, latest day first."""
        q = (
            select(EssayPracticeRow)
            .where(EssayPracticeRow.student_id == student_id)
            .order_by(EssayPracticeRow.day.desc())
            .limit(limit)
        )
        return [await self._view(r) for r in await self._s.scalars(q)]

    async def days(self, student_id: UUID, limit: int) -> list[dt.date]:
        """The days with an entry, newest first (nothing is opened)."""
        q = (
            select(EssayPracticeRow.day)
            .where(EssayPracticeRow.student_id == student_id)
            .order_by(EssayPracticeRow.day.desc())
            .limit(limit)
        )
        return list(await self._s.scalars(q))


def _entry(row: EssayGalleryRow) -> GalleryEntry:
    return GalleryEntry(
        id=row.id,
        essay_id=row.essay_id,
        student_id=row.student_id,
        version=row.version,
        published_at=row.created_at,
        title=row.title,
        prompt_text=row.prompt_text,
        word_limit=row.word_limit,
        targets=_targets(row.targets or []),
    )


class SqlGalleryRepository:
    """Published versions in `admission.essay_gallery`."""

    def __init__(self, session: AsyncSession) -> None:
        """Keep the session."""
        self._s = session

    async def _row(self, essay_id: UUID) -> EssayGalleryRow | None:
        q = select(EssayGalleryRow).where(EssayGalleryRow.essay_id == essay_id)
        return (await self._s.scalars(q)).first()

    async def get(self, essay_id: UUID) -> GalleryEntry | None:
        """The published entry of an essay, or None."""
        row = await self._row(essay_id)
        return None if row is None else _entry(row)

    async def publish(self, entry: GalleryEntry) -> GalleryEntry:
        """Publish a version; a published essay moves to the new version."""
        row = await self._row(entry.essay_id)
        if row is None:
            row = EssayGalleryRow(
                id=entry.id, essay_id=entry.essay_id, student_id=entry.student_id
            )
            self._s.add(row)
        row.version = entry.version
        row.title = entry.title
        row.prompt_text = entry.prompt_text
        row.word_limit = entry.word_limit
        row.targets = [_target_json(t) for t in entry.targets]
        if entry.published_at is not None:
            row.created_at = entry.published_at
        await self._s.flush()
        return _entry(row)

    async def unpublish(self, essay_id: UUID) -> None:
        """Take the essay out of the gallery."""
        await self._s.execute(
            delete(EssayGalleryRow).where(EssayGalleryRow.essay_id == essay_id)
        )

    async def by_student(self, student_id: UUID) -> list[GalleryEntry]:
        """One student's published entries, newest first."""
        q = (
            select(EssayGalleryRow)
            .where(EssayGalleryRow.student_id == student_id)
            .order_by(EssayGalleryRow.created_at.desc(), EssayGalleryRow.id)
        )
        return [_entry(r) for r in await self._s.scalars(q)]

    async def others(self, student_id: UUID, limit: int) -> list[GalleryEntry]:
        """The newest entries of every other student."""
        q = (
            select(EssayGalleryRow)
            .where(EssayGalleryRow.student_id != student_id)
            .order_by(EssayGalleryRow.created_at.desc(), EssayGalleryRow.id)
            .limit(limit)
        )
        return [_entry(r) for r in await self._s.scalars(q)]


class SqlSlotRepository:
    """Slot assignments in `admission.essay_slots`."""

    def __init__(self, session: AsyncSession) -> None:
        """Keep the session."""
        self._s = session

    async def for_student(
        self, student_id: UUID, institution_id: UUID | None = None
    ) -> list[SlotAssignment]:
        """A student's slots, of one university or of all of them."""
        q = select(EssaySlotRow).where(EssaySlotRow.student_id == student_id)
        if institution_id is not None:
            q = q.where(EssaySlotRow.institution_id == institution_id)
        q = q.order_by(EssaySlotRow.institution_id, EssaySlotRow.slot)
        return [
            SlotAssignment(r.student_id, r.institution_id, r.slot, r.essay_id)
            for r in await self._s.scalars(q)
        ]

    async def put(self, slot: SlotAssignment) -> None:
        """Place the essay; it leaves any other slot of the same university."""
        await self._s.execute(
            delete(EssaySlotRow).where(
                EssaySlotRow.student_id == slot.student_id,
                EssaySlotRow.institution_id == slot.institution_id,
                or_(
                    EssaySlotRow.slot == slot.slot,
                    EssaySlotRow.essay_id == slot.essay_id,
                ),
            )
        )
        self._s.add(
            EssaySlotRow(
                id=new_id(),
                student_id=slot.student_id,
                institution_id=slot.institution_id,
                slot=slot.slot,
                essay_id=slot.essay_id,
            )
        )
        await self._s.flush()

    async def clear(self, student_id: UUID, institution_id: UUID, slot: str) -> None:
        """Empty one slot."""
        await self._s.execute(
            delete(EssaySlotRow).where(
                and_(
                    EssaySlotRow.student_id == student_id,
                    EssaySlotRow.institution_id == institution_id,
                    EssaySlotRow.slot == slot,
                )
            )
        )


class SqlGroupLabelRepository:
    """Group labels in `admission.prompt_group_labels`."""

    def __init__(self, session: AsyncSession) -> None:
        """Keep the session."""
        self._s = session

    async def get_many(self, hashes: Sequence[str]) -> dict[str, GroupLabel]:
        """The stored labels among `hashes`."""
        if not hashes:
            return {}
        q = select(PromptGroupLabelRow).where(
            PromptGroupLabelRow.members_hash.in_(list(hashes))
        )
        return {
            r.members_hash: GroupLabel(
                r.members_hash, r.label_ru, r.label_en, r.label_uz, r.model
            )
            for r in await self._s.scalars(q)
        }

    async def put_many(self, labels: Sequence[GroupLabel]) -> None:
        """Store labels; one already stored for the same members is kept."""
        if not labels:
            return
        stmt = pg_insert(PromptGroupLabelRow).values(
            [
                {
                    "members_hash": g.members_hash,
                    "label_ru": g.ru,
                    "label_en": g.en,
                    "label_uz": g.uz,
                    "model": g.model,
                }
                for g in labels
            ]
        )
        await self._s.execute(stmt.on_conflict_do_nothing())


class SqlIdeaFitCache:
    """Idea fits in `admission.idea_fits`."""

    def __init__(self, session: AsyncSession) -> None:
        """Keep the session."""
        self._s = session

    async def get(self, student_id: UUID, text_digest: str) -> StoredIdeaFit | None:
        """The cached fit of the idea, or None."""
        row = await self._s.get(IdeaFitRow, (student_id, text_digest))
        if row is None:
            return None
        p = row.payload
        return StoredIdeaFit(
            version=row.version,
            available=bool(p["available"]),
            model=str(p["model"]),
            delta=float(p["delta"]),
            items=tuple((str(k), float(d), int(sc)) for k, d, sc in p["items"]),
        )

    async def put(self, student_id: UUID, text_digest: str, fit: StoredIdeaFit) -> None:
        """Store or replace the fit of the idea."""
        payload = {
            "available": fit.available,
            "model": fit.model,
            "delta": fit.delta,
            "items": [list(i) for i in fit.items],
        }
        stmt = pg_insert(IdeaFitRow).values(
            student_id=student_id,
            text_digest=text_digest,
            version=fit.version,
            payload=payload,
        )
        await self._s.execute(
            stmt.on_conflict_do_update(
                index_elements=["student_id", "text_digest"],
                set_={
                    "version": stmt.excluded.version,
                    "payload": stmt.excluded.payload,
                    "created_at": sa_func.now(),
                },
            )
        )
