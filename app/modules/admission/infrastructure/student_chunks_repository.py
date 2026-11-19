"""PostgreSQL adapters under the student data search: chunk store and collector."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import datetime
from typing import Any
from uuid import UUID

from app.modules.admission.domain.courses import Course
from app.modules.admission.domain.student_chunks import (
    MAX_VECTOR_DISTANCE,
    Chunk,
    make_chunks,
)
from app.modules.admission.infrastructure.orm import (
    CareerPlanRow,
    CourseRow,
    DocumentRow,
    DocumentVersionRow,
    EssayRow,
    InstitutionRow,
    ItemRow,
    ListEntryRow,
    OpportunityPlanEntryRow,
    OpportunityRow,
    ProfileRow,
    ProfileWordsRow,
    ProgramRow,
    ScoreEntryRow,
    ScoreTestRow,
    StudentChunkRow,
    TaskRow,
)
from app.modules.admission.ports.courses import CourseSources
from app.shared.db.embeddings import EMBEDDING_DIMS
from app.shared.db.embeddings import Embedding as EmbeddingRow
from app.shared.db.halfvec import HalfVec

from sqlalchemy import Float, Select, delete, func, literal, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_BATCH = 200
_TITLE = 300
_Row = StudentChunkRow

# Vectors are shared by `content_hash` across modules: drop only those no row of
# admission, notebooks, knowledge or the web page cache still points at.
_ORPHANS = text("""
    DELETE FROM vectors.embeddings e
    WHERE e.content_hash = ANY(CAST(:hashes AS char(64)[]))
      AND NOT EXISTS (SELECT 1 FROM admission.admission_student_chunks
                      WHERE content_hash = e.content_hash)
      AND NOT EXISTS (SELECT 1 FROM notebooks.passages
                      WHERE content_hash = e.content_hash)
      AND NOT EXISTS (SELECT 1 FROM knowledge.entries
                      WHERE content_hash = e.content_hash)
      AND NOT EXISTS (SELECT 1 FROM ai.web_pages
                      WHERE content_hash = e.content_hash)
    """)


def _chunk(row: Any) -> Chunk:
    return Chunk(row.source, row.ref_id, row.title, row.body, row.seq)


class SqlChunkStore:
    """`ChunkStore` over `admission.admission_student_chunks` and `vectors`."""

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        """Keep the session factory; each call is its own transaction."""
        self._sm = sessionmaker

    async def replace(
        self, student_id: UUID, chunks: Sequence[Chunk], now: datetime
    ) -> int:
        """Delete the student's chunks and insert the new ones."""
        rows = [
            {
                "student_id": student_id,
                "source": c.source,
                "ref_id": c.ref_id[:80],
                "seq": c.seq,
                "title": c.title[:_TITLE],
                "body": c.body,
                "content_hash": c.content_hash,
                "updated_at": now,
            }
            for c in chunks
        ]
        async with self._sm() as session, session.begin():
            await session.execute(delete(_Row).where(_Row.student_id == student_id))
            for i in range(0, len(rows), _BATCH):
                stmt = insert(_Row).values(rows[i : i + _BATCH])
                await session.execute(stmt.on_conflict_do_nothing())
            if not rows:
                await session.execute(self._marker(student_id, now))
        return len(rows)

    @staticmethod
    def _marker(student_id: UUID, now: datetime) -> Any:
        """An empty student still gets a stamp, so it is not re-read on each search."""
        return insert(_Row).values(
            student_id=student_id,
            source="marker",
            ref_id="",
            seq=0,
            title="",
            body="",
            content_hash="0" * 64,
            updated_at=now,
        )

    async def delete(self, student_id: UUID) -> None:
        """Drop every chunk of the student and the vectors nothing else uses."""
        async with self._sm() as session, session.begin():
            hashes = list(
                await session.scalars(
                    select(_Row.content_hash)
                    .where(_Row.student_id == student_id)
                    .distinct()
                )
            )
            await session.execute(delete(_Row).where(_Row.student_id == student_id))
            if hashes:
                await session.execute(_ORPHANS, {"hashes": hashes})

    async def ref_count(self, student_id: UUID) -> int:
        """Distinct indexed rows (the marker is not one)."""
        stmt = select(func.count()).select_from(
            select(_Row.source, _Row.ref_id)
            .where(_Row.student_id == student_id, _Row.source != "marker")
            .distinct()
            .subquery()
        )
        async with self._sm() as session:
            return int(await session.scalar(stmt) or 0)

    async def indexed_at(self, student_id: UUID) -> datetime | None:
        """The newest chunk stamp of the student."""
        async with self._sm() as session:
            stamp: datetime | None = await session.scalar(
                select(func.max(_Row.updated_at)).where(_Row.student_id == student_id)
            )
            return stamp

    async def text_search(
        self,
        student_id: UUID,
        tokens: Sequence[str],
        sources: Sequence[str],
        limit: int,
    ) -> list[Chunk]:
        """Any-token prefix match on the `simple` vector, by `ts_rank_cd`."""
        query = func.to_tsquery("simple", " | ".join(f"{t}:*" for t in tokens))
        rank = func.ts_rank_cd(_Row.tsv, query)
        stmt = (
            self._scope(select(_Row), student_id, sources)
            .where(_Row.tsv.op("@@")(query))
            .order_by(rank.desc(), _Row.source, _Row.ref_id, _Row.seq)
            .limit(limit)
        )
        async with self._sm() as session:
            return [_chunk(r) for r in (await session.scalars(stmt))]

    async def vector_search(
        self,
        student_id: UUID,
        model: str,
        vector: Sequence[float],
        sources: Sequence[str],
        limit: int,
    ) -> list[Chunk]:
        """The student's chunks nearest to the vector by cosine distance."""
        if len(vector) != EMBEDDING_DIMS:
            return []
        point = literal(list(vector), HalfVec(EMBEDDING_DIMS))
        distance = EmbeddingRow.embedding.op("<=>", return_type=Float)(point)
        stmt = (
            self._scope(select(_Row), student_id, sources)
            .join(
                EmbeddingRow,
                (EmbeddingRow.content_hash == _Row.content_hash)
                & (EmbeddingRow.model == model),
            )
            .where(distance < MAX_VECTOR_DISTANCE)
            .order_by(distance, _Row.source, _Row.ref_id, _Row.seq)
            .limit(limit)
        )
        async with self._sm() as session:
            return [_chunk(r) for r in (await session.scalars(stmt))]

    @staticmethod
    def _scope(
        stmt: Select[Any], student_id: UUID, sources: Sequence[str]
    ) -> Select[Any]:
        stmt = stmt.where(_Row.student_id == student_id, _Row.source != "marker")
        return stmt.where(_Row.source.in_(sources)) if sources else stmt


def _flat(value: Any) -> str:
    """All text and numbers inside a JSON value, in order, space-joined."""
    if value is None or isinstance(value, bool):
        return ""
    if isinstance(value, dict):
        return " ".join(filter(None, (_flat(v) for v in value.values())))
    if isinstance(value, (list, tuple)):
        return " ".join(filter(None, (_flat(v) for v in value)))
    return str(value).strip()


def _lines(*parts: tuple[str, Any]) -> str:
    """`label: value` lines for the parts that have a value."""
    out = []
    for label, value in parts:
        text = value if isinstance(value, str) else _flat(value)
        if text.strip():
            out.append(f"{label}: {text.strip()}")
    return "\n".join(out)


class SqlChunkCollector:
    """`ChunkCollector` reading the admission tables of one student."""

    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        course_sources: CourseSources | None = None,
    ) -> None:
        """Keep the session factory and the lyceum courses port (optional)."""
        self._sm = sessionmaker
        self._courses_port = course_sources

    async def ref_count(self, student_id: UUID) -> int:
        """Distinct (source, ref_id) pairs `collect` yields, by counting queries."""
        sid = student_id
        simple = (ItemRow, EssayRow, TaskRow, ScoreEntryRow, DocumentRow, CourseRow)
        counts = [
            select(func.count()).select_from(m).where(m.student_id == sid)
            for m in simple
        ]
        counts += [
            select(func.count())
            .select_from(CourseRow)
            .where(
                CourseRow.student_id == sid,
                CourseRow.grade.is_not(None),
                CourseRow.grade != "",
            ),
            select(func.count())
            .select_from(OpportunityPlanEntryRow)
            .join(
                OpportunityRow,
                OpportunityRow.id == OpportunityPlanEntryRow.opportunity_id,
            )
            .where(OpportunityPlanEntryRow.student_id == sid),
            select(func.count())
            .select_from(ListEntryRow)
            .join(InstitutionRow, InstitutionRow.id == ListEntryRow.institution_id)
            .where(ListEntryRow.student_id == sid),
        ]
        async with self._sm() as s:
            total = 0
            for q in counts:
                total += int(await s.scalar(q) or 0)
            for model in (CareerPlanRow,):
                total += int(
                    await s.scalar(
                        select(func.count())
                        .select_from(model)
                        .where(model.student_id == sid)
                    )
                    or 0
                )
            has_profile = await s.scalar(
                select(func.count())
                .select_from(ProfileRow)
                .where(ProfileRow.student_id == sid)
            ) or await s.scalar(
                select(func.count())
                .select_from(ProfileWordsRow)
                .where(ProfileWordsRow.student_id == sid)
            )
            total += 1 if has_profile else 0
            stored = await self._stored_refs(s, sid)
        live = await self._live_courses(sid, stored)
        return total + len(live) + sum(1 for c in live if c.grade)

    @staticmethod
    async def _stored_refs(s: AsyncSession, sid: UUID) -> set[str]:
        rows = await s.scalars(
            select(CourseRow.source_ref).where(
                CourseRow.student_id == sid, CourseRow.source_ref.is_not(None)
            )
        )
        return {r for r in rows if r}

    async def _live_courses(self, sid: UUID, stored: set[str]) -> list[Course]:
        """Lyceum subjects the academic module knows and no stored row mirrors."""
        if self._courses_port is None:
            return []
        found = await self._courses_port.academic_courses(sid)
        return [c for c in found if (c.source_ref or c.title) not in stored]

    async def collect(self, student_id: UUID) -> list[Chunk]:
        """Chunks of every searchable source of the student."""
        async with self._sm() as s:
            out: list[Chunk] = []
            for part in (
                await self._profile(s, student_id),
                await self._items(s, student_id),
                await self._essays(s, student_id),
                await self._tasks(s, student_id),
                await self._scores(s, student_id),
                await self._documents(s, student_id),
                await self._career(s, student_id),
                await self._lists(s, student_id),
                await self._opportunities(s, student_id),
                await self._courses(s, student_id),
            ):
                out.extend(part)
            return out

    async def latest_change(self, student_id: UUID) -> datetime | None:
        """The newest change over the student's rows (deleted rows are not seen)."""
        models = (
            ProfileRow,
            ProfileWordsRow,
            ItemRow,
            EssayRow,
            TaskRow,
            ScoreEntryRow,
            DocumentRow,
            CareerPlanRow,
            ListEntryRow,
            CourseRow,
        )
        queries = [
            select(func.max(m.updated_at)).where(m.student_id == student_id)
            for m in models
        ]
        queries.append(
            select(func.max(OpportunityPlanEntryRow.created_at)).where(
                OpportunityPlanEntryRow.student_id == student_id
            )
        )
        async with self._sm() as s:
            stamps = [await s.scalar(q) for q in queries]
        found = [t for t in stamps if t is not None]
        return max(found) if found else None

    async def _profile(self, s: AsyncSession, sid: UUID) -> list[Chunk]:
        row = await s.scalar(select(ProfileRow).where(ProfileRow.student_id == sid))
        words = await s.scalar(
            select(ProfileWordsRow).where(ProfileWordsRow.student_id == sid)
        )
        if row is None and words is None:
            return []
        body = _lines(
            ("Career plan", row.career_plan if row else ""),
            ("Intended majors", row.intended_majors if row else []),
            ("Minors", row.minors if row else []),
            ("Answers", row.answers if row else {}),
            ("Words", words.words if words else []),
        )
        return make_chunks("profile", str(sid), "Profile", body)

    async def _items(self, s: AsyncSession, sid: UUID) -> list[Chunk]:
        rows = await s.scalars(select(ItemRow).where(ItemRow.student_id == sid))
        return self._each(
            "item",
            rows,
            lambda r: (
                f"{r.position} — {r.org}",
                _lines(
                    ("Kind", r.kind),
                    ("Description", r.description),
                    ("Role", r.role),
                    ("Outcome", r.outcome),
                ),
            ),
        )

    async def _essays(self, s: AsyncSession, sid: UUID) -> list[Chunk]:
        """Index the plaintext columns only; sealed essay text never leaves."""
        rows = await s.execute(
            select(EssayRow.id, EssayRow.kind, EssayRow.prompt_text).where(
                EssayRow.student_id == sid
            )
        )
        return self._each(
            "essay",
            rows,
            lambda r: (
                r.prompt_text[:80] or "Essay",
                _lines(("Kind", r.kind), ("Prompt", r.prompt_text)),
            ),
        )

    async def _tasks(self, s: AsyncSession, sid: UUID) -> list[Chunk]:
        rows = await s.scalars(select(TaskRow).where(TaskRow.student_id == sid))
        return self._each(
            "task",
            rows,
            lambda r: (
                r.title,
                _lines(
                    ("Description", r.description),
                    ("Status", r.status),
                    ("Steps", [st.get("title") for st in r.steps]),
                ),
            ),
        )

    async def _scores(self, s: AsyncSession, sid: UUID) -> list[Chunk]:
        stmt = (
            select(ScoreEntryRow, ScoreTestRow)
            .join(ScoreTestRow, ScoreTestRow.id == ScoreEntryRow.test_id)
            .where(ScoreEntryRow.student_id == sid)
        )
        out: list[Chunk] = []
        for entry, test in (await s.execute(stmt)).all():
            title = entry.label or str(test.names.get("en") or test.key)
            body = _lines(
                ("Test", " / ".join(str(v) for v in test.names.values())),
                ("Status", entry.status),
                ("Level", entry.level),
                ("Sections", entry.sections),
                ("Total", entry.total),
            )
            out.extend(make_chunks("test_score", str(entry.id), title, body))
        return out

    async def _documents(self, s: AsyncSession, sid: UUID) -> list[Chunk]:
        rows = await s.scalars(select(DocumentRow).where(DocumentRow.student_id == sid))
        out: list[Chunk] = []
        for doc in rows:
            version = await s.scalar(
                select(DocumentVersionRow)
                .where(DocumentVersionRow.document_id == doc.id)
                .order_by(DocumentVersionRow.version.desc())
                .limit(1)
            )
            body = _lines(
                ("Kind", doc.kind),
                ("Review", doc.review_status),
                ("Version", version.version if version else ""),
                ("Uploaded", version.uploaded_at.date().isoformat() if version else ""),
            )
            out.extend(make_chunks("document", str(doc.id), doc.kind, body))
        return out

    async def _career(self, s: AsyncSession, sid: UUID) -> list[Chunk]:
        row = await s.scalar(
            select(CareerPlanRow).where(CareerPlanRow.student_id == sid)
        )
        if row is None:
            return []
        body = _lines(
            ("Answers", row.answers),
            ("Professions", row.professions),
            ("Majors", row.majors),
            ("Minors", row.minors),
            ("Fit", row.fit),
            ("Spike", row.spike),
        )
        return make_chunks("career", str(sid), "Career plan", body)

    async def _lists(self, s: AsyncSession, sid: UUID) -> list[Chunk]:
        stmt = (
            select(ListEntryRow, InstitutionRow, ProgramRow)
            .join(InstitutionRow, InstitutionRow.id == ListEntryRow.institution_id)
            .outerjoin(ProgramRow, ProgramRow.id == ListEntryRow.program_id)
            .where(ListEntryRow.student_id == sid)
        )
        out: list[Chunk] = []
        for entry, inst, prog in (await s.execute(stmt)).all():
            body = _lines(
                ("Institution", f"{inst.name} {inst.name_local or ''}"),
                ("Program", prog.name if prog else ""),
                ("Country", inst.country),
                ("Round", entry.round),
                ("Status", entry.status),
                ("Bucket", entry.bucket),
            )
            out.extend(make_chunks("list", str(entry.id), inst.name, body))
        return out

    async def _opportunities(self, s: AsyncSession, sid: UUID) -> list[Chunk]:
        stmt = (
            select(OpportunityPlanEntryRow, OpportunityRow)
            .join(
                OpportunityRow,
                OpportunityRow.id == OpportunityPlanEntryRow.opportunity_id,
            )
            .where(OpportunityPlanEntryRow.student_id == sid)
        )
        out: list[Chunk] = []
        for entry, opp in (await s.execute(stmt)).all():
            body = _lines(
                ("Kind", opp.kind),
                ("Details", opp.payload),
                ("Planned grade", entry.planned_grade),
                ("Note", entry.note),
            )
            out.extend(make_chunks("opportunity", str(opp.id), opp.title, body))
        return out

    async def _courses(self, s: AsyncSession, sid: UUID) -> list[Chunk]:
        rows = list(
            await s.scalars(select(CourseRow).where(CourseRow.student_id == sid))
        )
        stored = {r.source_ref for r in rows if r.source_ref}
        live = await self._live_courses(sid, stored)
        pairs: list[tuple[str, Any]] = [(str(r.id), r) for r in rows]
        pairs += [(f"academic:{c.source_ref or c.title}", c) for c in live]
        out: list[Chunk] = []
        for ref, r in pairs:
            out.extend(
                make_chunks(
                    "course",
                    ref,
                    r.title,
                    _lines(
                        ("Provider", r.provider),
                        ("Level", r.level),
                        ("Year", r.year),
                    ),
                )
            )
            if r.grade:
                out.extend(make_chunks("grade", ref, r.title, f"Grade: {r.grade}"))
        return out

    @staticmethod
    def _each(source: Any, rows: Iterable[Any], fmt: Any) -> list[Chunk]:
        out: list[Chunk] = []
        for r in rows:
            title, body = fmt(r)
            out.extend(make_chunks(source, str(r.id), title, body))
        return out
