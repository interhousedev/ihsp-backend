"""Use case: global search over the student's own data (WEB-4, UF-WEB-14)."""

from app.interfaces.http.v1.composition.application.views import (
    homework_item,
    lesson_items,
    load_users,
    subject_ref,
)
from app.interfaces.http.v1.composition.ports import FilesViews, JsonObject
from app.shared.actor import Actor, Role
from app.shared.base_error import ValidationFailedError
from app.shared.contracts.academic import (
    ClassworkQueries,
    MarksQueries,
    ScheduleQueries,
)
from app.shared.contracts.flashcards import FlashcardsApi
from app.shared.contracts.identity import IdentityDirectory

MIN_QUERY_LENGTH = 2
GROUP_LIMIT = 5


class SearchAll:
    """Finds subjects, lessons, homework, files and flash card sets by text."""

    def __init__(
        self,
        *,
        identity: IdentityDirectory,
        schedule: ScheduleQueries,
        classwork: ClassworkQueries,
        marks: MarksQueries,
        files: FilesViews,
        flashcards: FlashcardsApi,
        limit: int = GROUP_LIMIT,
    ) -> None:
        """Store the collaborators; `limit` caps every result group."""
        self.identity = identity
        self.schedule = schedule
        self.classwork = classwork
        self.marks = marks
        self.files = files
        self.flashcards = flashcards
        self.limit = limit

    async def execute(self, actor: Actor, query: str) -> JsonObject:
        """Return `SearchResults`; student-only groups are empty for staff."""
        text = query.strip()
        if len(text) < MIN_QUERY_LENGTH:
            raise ValidationFailedError(params={"min_length": MIN_QUERY_LENGTH})
        student = Role.STUDENT in actor.roles
        files = await self.files.search_files(actor.user_id, text, self.limit)
        return {
            "subjects": await self._subjects(actor, text) if student else [],
            "lessons": await self._lessons(actor, text),
            "homework": await self._homework(actor, text) if student else [],
            "files": files[: self.limit],
            "flashcard_sets": (
                await self._flashcard_sets(actor, text) if student else []
            ),
        }

    async def _subjects(self, actor: Actor, text: str) -> list[JsonObject]:
        needle = text.casefold()
        summaries = await self.marks.subjects_summary(actor.user_id, None)
        found = sorted(
            (s for s in summaries if needle in s.name.casefold()),
            key=lambda s: s.name.casefold(),
        )
        return [subject_ref(s.subject_id, s.name) for s in found[: self.limit]]

    async def _lessons(self, actor: Actor, text: str) -> list[JsonObject]:
        refs = await self.schedule.search_lessons(actor.user_id, text, self.limit)
        return await lesson_items(self.identity, refs[: self.limit])

    async def _homework(self, actor: Actor, text: str) -> list[JsonObject]:
        needle = text.casefold()
        entries = await self.classwork.homework(actor.user_id, None, None, None)
        found = sorted(
            (
                e
                for e in entries
                if needle in (e["lesson"].homework_text or "").casefold()
            ),
            key=lambda e: e["lesson"].date,
            reverse=True,
        )[: self.limit]
        teachers = await load_users(
            self.identity,
            [e["lesson"].teacher_id for e in found if e["lesson"].teacher_id],
        )
        return [homework_item(entry, teachers) for entry in found]

    async def _flashcard_sets(self, actor: Actor, text: str) -> list[JsonObject]:
        needle = text.casefold()
        sets = await self.flashcards.list_sets(actor.user_id)
        found = [s for s in sets if needle in str(s.get("title", "")).casefold()]
        return [
            {
                "id": s["id"],
                "title": s["title"],
                "description": s.get("description"),
                "source": s.get("source", "manual"),
                "card_count": s.get("card_count", 0),
                # The contract's list_sets has no study counters yet; 0 until it does.
                "due_today": s.get("due_today", 0),
                "new_today": s.get("new_today", 0),
            }
            for s in found[: self.limit]
        ]
