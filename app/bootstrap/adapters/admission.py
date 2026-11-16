"""Adapters of the admission module: group membership and course sources."""

from collections.abc import Sequence
from typing import Any
from uuid import UUID

from app.modules.admission.domain.courses import Course
from app.shared.actor import SYSTEM_ACTOR, Actor
from app.shared.contracts.academic import ScheduleQueries, StudentRef
from app.shared.contracts.web_search import SearchCall, SearchReply, WebSearchApi


class AdmissionMembershipAdapter:
    """AcademicMembership over the schedule queries."""

    def __init__(self, schedule: ScheduleQueries) -> None:
        """Keep the schedule queries."""
        self._schedule = schedule

    async def student(self, user_id: UUID) -> StudentRef | None:
        """Return the active student record or None."""
        ref = await self._schedule.get_student(user_id)
        return ref if ref is not None and ref.status == "active" else None

    async def group_ids_for(
        self, user_ids: Sequence[UUID]
    ) -> dict[UUID, frozenset[UUID]]:
        """Return the group of each active student."""
        out: dict[UUID, frozenset[UUID]] = {}
        for user_id in user_ids:
            ref = await self.student(user_id)
            if ref is not None:
                out[user_id] = frozenset({ref.group_id})
        return out

    async def students_in_groups(self, group_ids: Sequence[UUID]) -> list[UUID]:
        """Return the groups' active students."""
        return await self._schedule.group_user_ids(group_ids)


class AdmissionCourseSourcesAdapter:
    """Lyceum subjects from academic marks; enrolments from LMS when it is built."""

    def __init__(self, marks: Any, lms_courses: Any | None) -> None:
        """Keep `MarksQueries` and `ListMyCourses` (None without LMS)."""
        self._marks = marks
        self._lms = lms_courses

    async def academic_courses(self, student_id: UUID) -> list[Course]:
        """Return the current semester's subjects with the semester mark."""
        subjects = await self._marks.subjects_summary(student_id, None)
        return [
            Course(
                student_id=student_id,
                source="academic",
                source_ref=str(s.subject_id),
                title=s.name[:200],
                grade=None if s.semester_mark is None else f"{s.semester_mark:.2f}",
            )
            for s in subjects
        ]

    async def lms_courses(self, actor: Actor) -> list[Course]:
        """Return the actor's LMS enrolments; empty without LMS."""
        if self._lms is None:
            return []
        view = await self._lms.execute(actor)
        return [
            Course(
                student_id=actor.user_id,
                source="lms",
                source_ref=str(card.id),
                title=card.title[:200],
                provider="LMS",
                grade=None if card.progress_pct is None else f"{card.progress_pct}%",
            )
            for card in view.enrolled
        ]


class AdmissionLmsCourseLookupAdapter:
    """Titles of LMS courses linked from opportunities."""

    def __init__(self, workspace: Any) -> None:
        """Keep the LMS authoring workspace."""
        self._workspace = workspace

    async def course_title(self, course_id: UUID) -> str | None:
        """Return the course title, or None when the course does not exist."""
        brief = await self._workspace.course_brief(course_id)
        return None if brief is None else str(brief.title)[:200]


class AdmissionWebSearchAdapter:
    """WebSearchGateway of the intake over the shared web search (system actor)."""

    def __init__(self, search: WebSearchApi) -> None:
        """Keep the shared web search."""
        self._search = search

    async def search(self, call: SearchCall) -> SearchReply:
        """Run one fast search and return its hits."""
        outcome = await self._search.search(
            SYSTEM_ACTOR, query=call.query, locale=call.language, kind="fast"
        )
        return SearchReply(
            hits=outcome.hits[: call.max_results],
            usage={},
            cost_micro=outcome.cost_micro,
            notice=outcome.notice,
        )
