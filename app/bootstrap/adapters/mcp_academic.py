"""McpAcademicTools over the academic module."""

from collections.abc import Sequence
from dataclasses import asdict
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from app.interfaces.mcp.errors import McpNotFoundError
from app.interfaces.mcp.untrusted import safe_external_url
from app.modules.academic.application.schedule.request_student_refresh import (
    RequestStudentRefresh,
    sync_error_code,
)
from app.modules.academic.application.schedule.student_sync_jobs import StudentSyncJob
from app.modules.academic.domain.classwork.errors import LessonNotFoundError
from app.modules.academic.domain.schedule.errors import TeacherNotFoundError
from app.modules.academic.infrastructure.schedule.lesson_fetch_store import (
    RedisLessonFetchStore,
)
from app.modules.academic.infrastructure.schedule.sync_cooldown import (
    RedisSyncCooldown,
)
from app.shared.actor import Actor
from app.shared.contracts.links import ResourceRef
from app.shared.contracts.mcp_academic import MaterialFetch, McpAcademicTools

import structlog

if TYPE_CHECKING:
    from app.bootstrap.container import Container

log = structlog.get_logger(__name__)

FETCH_TASK = "academic.fetch_lesson_materials"
_KINDS = ("homework", "classwork", "video", "other")


def _job_view(job: StudentSyncJob | None) -> dict[str, Any] | None:
    if job is None:
        return None
    return {
        "status": job.status,
        "requested_at": job.requested_at,
        "started_at": job.started_at,
        "finished_at": job.finished_at,
        "marks_count": job.marks_count,
        "error": sync_error_code(job.last_error),
    }


def _resource(ref: ResourceRef) -> dict[str, Any]:
    return {
        "link_id": ref.link_id,
        "kind": ref.kind,
        "title": ref.title,
        "short_url": ref.short_url,
        "file_id": ref.file_id,
        "source": ref.source,
        "author": ref.author_first_name,
        "external_url": safe_external_url(ref.target_url),
    }


def _material_kind(ref: ResourceRef) -> str:
    return "homework" if ref.role == "homework" else ref.material_kind or "other"


class McpAcademicToolsAdapter:
    """Reads the modules lazily: a process that serves no MCP never touches them."""

    def __init__(self, container: "Container") -> None:
        """Keep the container; the store shares its Redis."""
        self._c = container
        self._store = RedisLessonFetchStore(container.redis)

    async def request_refresh(self, actor: Actor) -> dict[str, Any]:
        """Start a self-service sync, or return the job and retry_after_seconds."""
        c = self._c
        outcome = await RequestStudentRefresh(
            jobs=c.academic.emis_import.sync_jobs,
            kicker=c.kicker,
            clock=c.clock,
            cooldown=RedisSyncCooldown(c.redis),
            cooldown_seconds=c.settings.mcp.sync_cooldown_seconds,
        ).execute(actor)
        return {
            "status": outcome.status,
            "job": _job_view(outcome.job),
            "retry_after_seconds": outcome.retry_after_seconds,
        }

    async def sync_status(self, user_id: UUID) -> dict[str, Any]:
        """The user's sync job; errors only as fixed codes, never raw text."""
        job = await self._c.academic.emis_import.sync_jobs.get(user_id)
        return {"status": job.status if job else "never", "job": _job_view(job)}

    async def my_teachers(self, actor: Actor) -> list[dict[str, Any]]:
        """Teachers of the student's groups, with what the student page shows."""
        teachers = await self._c.academic.schedule.get_my_teachers.execute(actor)
        return [
            {
                "id": teacher.id,
                "first_name": teacher.first_name,
                "last_name": teacher.last_name,
                "middle_name": teacher.middle_name,
                "subjects": teacher.subjects,
                "contacts": teacher.contacts,
                "teaching_now": teacher.teaching_now,
                "current": teacher.current,
                "next": teacher.next,
            }
            for teacher in teachers
        ]

    async def teacher_timetable(
        self, actor: Actor, teacher_id: UUID, start: Any, end: Any  # noqa: ANN401
    ) -> list[dict[str, Any]]:
        """Timetable of a teacher of this student; another teacher is not found."""
        use_case = self._c.academic.schedule.get_teacher_timetable
        try:
            slots = await use_case.execute(actor, teacher_id, start, end)
        except TeacherNotFoundError as error:
            raise McpNotFoundError() from error
        return [asdict(slot) for slot in slots]

    async def gpa(self, user_id: UUID, semester: int | None) -> dict[str, Any]:
        """GPA as the platform calculates it; temporary marks stay separate."""
        queries = self._c.academic.marks.queries
        results = await queries.results(user_id, semester)
        summary = await queries.subjects_summary(user_id, results["semester"])
        temporary = {row.subject_id: row.gpa_with_temporary for row in summary}
        return {
            **results,
            "subjects": [
                {
                    "subject_id": row["subject_id"],
                    "name": row["name"],
                    "marks_count": row["marks_count"],
                    "semester_mark": row["semester_mark"],
                    "gpa_with_temporary": temporary.get(row["subject_id"]),
                }
                for row in results["subjects"]
            ],
        }

    async def lesson_detail(self, actor: Actor, lesson_id: UUID) -> dict[str, Any]:
        """Lesson, homework, materials by kind, own mark and attendance."""
        use_case = self._c.academic.classwork.student_lesson
        try:
            page = await use_case.execute(lesson_id, actor)
        except LessonNotFoundError as error:
            raise McpNotFoundError() from error
        refs = await self._c.links.public.lesson_resources(
            lesson_id, include_hidden=True
        )
        shown = [r for r in refs if not r.hidden or r.author_id == actor.user_id]
        materials: dict[str, list[dict[str, Any]]] = {kind: [] for kind in _KINDS}
        for ref in shown:
            if ref.role != "attachment":
                materials[_material_kind(ref)].append(_resource(ref))
        return {
            "lesson": page["lesson"],
            "homework": page["homework"],
            "materials": materials,
            "attachments": [_resource(r) for r in shown if r.role == "attachment"],
            "my_mark": page["my_mark"],
            "my_attendance": page["my_attendance"],
        }

    async def teacher_names(self, teacher_ids: Sequence[UUID]) -> dict[UUID, str]:
        """Display names of the teachers of lessons the caller already sees."""
        if not teacher_ids:
            return {}
        users = await self._c.identity.directory.get_users(list(teacher_ids))
        return {
            user_id: f"{user.first_name} {user.last_name}".strip()
            for user_id, user in users.items()
        }

    async def start_material_fetch(
        self, user_id: UUID, lesson_id: UUID
    ) -> MaterialFetch:
        """Join or start the fetch of a lesson; the audience is checked by the tool."""
        now = self._c.clock.now()
        job_id = uuid4().hex
        mine = MaterialFetch(job_id=job_id, status="running", started_at=now)
        busy = MaterialFetch(
            job_id=job_id, status="failed", started_at=now, reason="emis_busy"
        )
        current = await self._store.begin(lesson_id, user_id, mine)
        if current is None:
            return busy  # the user's cap: nothing stored, a later call may start it
        if current.job_id != job_id:
            return current
        try:
            await self._c.kicker.kick(
                FETCH_TASK,
                lesson_id=str(lesson_id),
                user_id=str(user_id),
                job_id=job_id,
            )
        except Exception:  # noqa: BLE001 - nobody would ever finish this job
            log.warning("lesson_materials_kick_failed", lesson_id=str(lesson_id))
            await self._store.finish(lesson_id, user_id, busy)
            return busy
        return mine

    async def material_fetch(self, lesson_id: UUID) -> MaterialFetch | None:
        """The fetch of a lesson, looked up by lesson and never by a client's job id."""
        return await self._store.get(lesson_id)


def build_academic_tools(container: "Container") -> McpAcademicTools:
    """Build the backend of the academic tools."""
    return McpAcademicToolsAdapter(container)
