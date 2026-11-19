"""Adapters of the admission module: group membership and course sources."""

from collections.abc import Sequence
from typing import Any
from uuid import UUID

from app.modules.admission.domain.courses import Course
from app.modules.ai.domain.assistant import Assistant
from app.modules.ai.domain.chat import ChatTier
from app.shared.actor import SYSTEM_ACTOR, Actor
from app.shared.contracts.academic import ScheduleQueries, StudentRef
from app.shared.contracts.admission_assistant import CourseHit
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

    def __init__(
        self,
        marks: Any,
        lms_courses: Any | None,
        lms_catalog: Any | None = None,
        lms_enroll: Any | None = None,
    ) -> None:
        """Keep `MarksQueries` and the LMS use cases (None without LMS)."""
        self._marks = marks
        self._lms = lms_courses
        self._catalog = lms_catalog
        self._enroll = lms_enroll

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

    async def lms_catalog(self, actor: Actor, query: str | None) -> list[Course]:
        """Return open public LMS courses; empty without LMS."""
        if self._catalog is None:
            return []
        cards = await self._catalog.execute(query=query, actor=actor)
        return [
            Course(
                student_id=actor.user_id,
                source="lms",
                source_ref=str(card.id),
                title=card.title[:200],
                provider="LMS",
            )
            for card in cards
            if not card.locked
        ]

    async def lms_find(
        self, actor: Actor, query: str | None, limit: int
    ) -> list[CourseHit]:
        """Open LMS courses the actor may see, with the actor's enrolments marked."""
        if self._catalog is None:
            return []
        cards = await self._catalog.execute(query=query, actor=actor)
        mine = {c.source_ref for c in await self.lms_courses(actor)}
        return [
            CourseHit(
                id=str(card.id),
                title=card.title,
                summary=card.summary or card.description,
                url=f"/courses/?lms={card.id}",
                enrolled=str(card.id) in mine,
            )
            for card in cards
            if not card.locked
        ][:limit]

    async def lms_enroll(self, actor: Actor, course_id: UUID) -> None:
        """Enroll the actor; a no-op without LMS."""
        if self._enroll is not None:
            await self._enroll.execute(actor, course_id)


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


class AdmissionUniChatsAdapter:
    """UniChats over the ai module: a fast-tier student chat per university.

    The deck researches every university the student lands on, so these chats
    must not spend the smart tier's few weekly requests (nor its budget weight).
    """

    def __init__(self, ai: Any) -> None:
        """Keep the ai services."""
        self._ai = ai

    async def start(self, actor: Actor, title: str) -> UUID:
        """Create the chat and give it the university's name."""
        chat = await self._ai.create_chat.execute(
            actor=actor, assistant=Assistant.STUDENT, tier=ChatTier.FAST
        )
        await self._ai.rename_chat.execute(actor=actor, chat_id=chat.id, title=title)
        return UUID(str(chat.id))

    async def alive(self, chat_id: UUID, owner_id: UUID) -> bool:
        """Whether the chat still exists and belongs to the owner."""
        return bool(await self._ai.public.chat_owner(chat_id) == owner_id)

    async def discard(self, actor: Actor, chat_id: UUID) -> None:
        """Delete a chat that lost a concurrent open."""
        await self._ai.delete_chat.execute(actor=actor, chat_id=chat_id)
