"""Use case: global search over the user's own data (WEB-4, UF-WEB-14).

Student groups: subjects, homework, marks, flash card sets. Groups for everyone:
lessons (by topic, subject, homework or a date), files, notebooks (title and source
titles) and library items.
"""

import datetime as dt
import re

from app.interfaces.http.v1.composition.application.views import (
    homework_item,
    lesson_items,
    load_users,
    subject_ref,
)
from app.interfaces.http.v1.composition.ports import (
    FilesViews,
    JsonObject,
    SearchSources,
)
from app.shared.actor import Actor, Role
from app.shared.base_error import ValidationFailedError
from app.shared.clock import Clock, local_today
from app.shared.contracts.academic import (
    ClassworkQueries,
    LessonRef,
    MarkRef,
    MarksQueries,
    ScheduleQueries,
)
from app.shared.contracts.flashcards import FlashcardsApi
from app.shared.contracts.identity import IdentityDirectory

MIN_QUERY_LENGTH = 2
GROUP_LIMIT = 5
DATE_PATTERN = re.compile(r"^(\d{1,2})[./-](\d{1,2})(?:[./-](\d{2,4}))?$")


def parse_date(text: str, today: dt.date) -> dt.date | None:
    """Read `2026-10-07`, `07.10.2026`, `7.10.26` or `07.10` (this year) as a date."""
    value = text.strip()
    try:
        return dt.date.fromisoformat(value)
    except ValueError:
        pass
    match = DATE_PATTERN.match(value)
    if match is None:
        return None
    day, month, year = match.groups()
    full_year = today.year if year is None else int(year)
    if year is not None and len(year) == 2:
        full_year += 2000
    try:
        return dt.date(full_year, int(month), int(day))
    except ValueError:
        return None


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
        sources: SearchSources,
        clock: Clock,
        limit: int = GROUP_LIMIT,
    ) -> None:
        """Store the collaborators; `limit` caps every result group."""
        self.identity = identity
        self.schedule = schedule
        self.classwork = classwork
        self.marks = marks
        self.files = files
        self.flashcards = flashcards
        self.sources = sources
        self.clock = clock
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
            "notebooks": await self.sources.notebooks(actor.user_id, text, self.limit),
            "marks": await self._marks(actor, text) if student else [],
            "library_items": await self.sources.library_items(actor, text, self.limit),
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
        day = parse_date(text, local_today(self.clock))
        if day is not None:
            refs = [*refs, *await self._lessons_on(actor, day)]
        unique = {ref.id: ref for ref in refs}
        return await lesson_items(self.identity, list(unique.values())[: self.limit])

    async def _lessons_on(self, actor: Actor, day: dt.date) -> list[LessonRef]:
        if Role.STUDENT in actor.roles:
            return await self.schedule.lessons_for_student(actor.user_id, day, day)
        return await self.schedule.lessons_for_teacher(actor.user_id, day, day)

    async def _marks(self, actor: Actor, text: str) -> list[JsonObject]:
        """The newest marks of the subjects whose name contains the text."""
        needle = text.casefold()
        summaries = await self.marks.subjects_summary(actor.user_id, None)
        subjects = [s for s in summaries if needle in s.name.casefold()]
        found: list[MarkRef] = []
        for subject in subjects[: self.limit]:
            found.extend(
                await self.marks.marks(actor.user_id, subject.subject_id, None, None)
            )
        found.sort(key=lambda m: m.date, reverse=True)
        return [
            {
                "subject": subject_ref(m.subject_id, m.subject_name),
                "type": m.type,
                "value": m.value,
                "date": m.date,
                "lesson_id": m.lesson_id,
            }
            for m in found[: self.limit]
        ]

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
