"""SQL storage of project-idea runs and curated helpers; each call is a session."""

from dataclasses import asdict
from typing import Any
from uuid import UUID

from app.modules.admission.domain.project_ideas import (
    Analog,
    Brief,
    Contacts,
    Helper,
    ProjectIdea,
    ProjectRun,
)
from app.modules.admission.infrastructure.orm.projects import (
    ProjectHelperRow,
    ProjectIdeaRunRow,
)

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


def _idea(raw: dict[str, Any]) -> ProjectIdea:
    return ProjectIdea(
        key=raw["key"],
        title=raw["title"],
        summary=raw["summary"],
        analogs=tuple(
            Analog(name=a["name"], where=a["where"], url=a.get("url"))
            for a in raw["analogs"]
        ),
        challenges=tuple(raw["challenges"]),
        application_effect=raw["application_effect"],
        first_steps=tuple(raw["first_steps"]),
        help_tags=tuple(raw["help_tags"]),
        deliverable=raw.get("deliverable", ""),
        measure=raw.get("measure", ""),
        why_you=raw.get("why_you", ""),
        weeks=raw.get("weeks"),
    )


def _run(row: ProjectIdeaRunRow) -> ProjectRun:
    return ProjectRun(
        id=row.id,
        student_id=row.student_id,
        locale=row.locale,
        brief=Brief(**row.brief),
        projects=tuple(_idea(p) for p in row.projects),
        model=row.model,
        search_used=row.search_used,
        created_at=row.created_at,
    )


def _helper(row: ProjectHelperRow) -> Helper:
    return Helper(
        id=row.id,
        kind=row.kind,
        name=row.name,
        description=dict(row.description or {}),
        tags=tuple(row.tags or ()),
        help_types=tuple(row.help_types or ()),
        expertise_areas=tuple(row.expertise_areas or ()),
        contacts=Contacts(**(row.contacts or {})),
        city=row.city,
        active=row.active,
        created_at=row.created_at,
        updated_at=row.updated_at,
        created_by=row.created_by,
    )


class SqlProjectRunRepository:
    """Runs of the student, newest first."""

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        """Keep the sessionmaker."""
        self._sm = sessionmaker

    async def add(self, run: ProjectRun, *, keep: int) -> None:
        """Store a run and drop the student's runs beyond the `keep` newest."""
        async with self._sm() as session, session.begin():
            session.add(
                ProjectIdeaRunRow(
                    id=run.id,
                    student_id=run.student_id,
                    locale=run.locale,
                    brief=asdict(run.brief),
                    projects=[asdict(p) for p in run.projects],
                    model=run.model,
                    search_used=run.search_used,
                )
            )
            await session.flush()
            stale = (
                await session.scalars(
                    select(ProjectIdeaRunRow.id)
                    .where(ProjectIdeaRunRow.student_id == run.student_id)
                    .order_by(
                        ProjectIdeaRunRow.created_at.desc(), ProjectIdeaRunRow.id.desc()
                    )
                    .offset(keep)
                )
            ).all()
            if stale:
                await session.execute(
                    delete(ProjectIdeaRunRow).where(ProjectIdeaRunRow.id.in_(stale))
                )

    async def history(self, student_id: UUID, *, limit: int) -> list[ProjectRun]:
        """The newest runs of the student, newest first."""
        async with self._sm() as session:
            rows = (
                await session.scalars(
                    select(ProjectIdeaRunRow)
                    .where(ProjectIdeaRunRow.student_id == student_id)
                    .order_by(
                        ProjectIdeaRunRow.created_at.desc(), ProjectIdeaRunRow.id.desc()
                    )
                    .limit(limit)
                )
            ).all()
        return [_run(r) for r in rows]

    async def latest(self, student_id: UUID) -> ProjectRun | None:
        """The newest run of the student."""
        runs = await self.history(student_id, limit=1)
        return runs[0] if runs else None

    async def get(self, student_id: UUID, run_id: UUID) -> ProjectRun | None:
        """One run of the student, else None."""
        async with self._sm() as session:
            row = await session.get(ProjectIdeaRunRow, run_id)
        return _run(row) if row and row.student_id == student_id else None


class SqlHelperRepository:
    """Curated helpers and organizations."""

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        """Keep the sessionmaker."""
        self._sm = sessionmaker

    async def list(self, *, active_only: bool) -> list[Helper]:
        """Helpers ordered by name."""
        stmt = select(ProjectHelperRow).order_by(ProjectHelperRow.name)
        if active_only:
            stmt = stmt.where(ProjectHelperRow.active.is_(True))
        async with self._sm() as session:
            return [_helper(r) for r in (await session.scalars(stmt)).all()]

    async def get(self, helper_id: UUID) -> Helper | None:
        """One helper, else None."""
        async with self._sm() as session:
            row = await session.get(ProjectHelperRow, helper_id)
        return _helper(row) if row else None

    async def save(self, helper: Helper) -> Helper:
        """Insert or overwrite a helper."""
        async with self._sm() as session, session.begin():
            row = await session.get(ProjectHelperRow, helper.id)
            if row is None:
                row = ProjectHelperRow(id=helper.id, created_by=helper.created_by)
                session.add(row)
            row.kind = helper.kind
            row.name = helper.name
            row.description = dict(helper.description)
            row.tags = list(helper.tags)
            row.help_types = list(helper.help_types)
            row.expertise_areas = list(helper.expertise_areas)
            row.contacts = asdict(helper.contacts)
            row.city = helper.city
            row.active = helper.active
            await session.flush()
            await session.refresh(row)
            return _helper(row)

    async def delete(self, helper_id: UUID) -> bool:
        """Delete a helper; return whether it existed."""
        async with self._sm() as session, session.begin():
            result = await session.execute(
                delete(ProjectHelperRow).where(ProjectHelperRow.id == helper_id)
            )
        return bool(getattr(result, "rowcount", 0))
