"""In-memory fakes of every service the MCP servers consume."""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any, Literal
from uuid import UUID

from app.shared.actor import Actor
from app.shared.base_error import NotFoundError, UnauthorizedError
from app.shared.contracts.academic import LessonRef, MarkRef, SubjectSummary
from app.shared.contracts.files import (
    FilePurpose,
    FileRef,
    FileScope,
    TextPage,
)
from app.shared.contracts.links import ResourceRef
from app.shared.ids import new_id
from app.shared.notifications import AuditDraft

# - - - Identity verifiers - - -


class FakeAccessVerifier:
    """OAuth access tokens: token -> (audience, actor)."""

    def __init__(self) -> None:
        self.tokens: dict[str, tuple[str, Actor]] = {}
        self.calls: list[tuple[str, str]] = []

    async def verify(self, token: str, *, audience: str) -> Actor:
        self.calls.append((token, audience))
        found = self.tokens.get(token)
        if found is None or found[0] != audience:
            raise UnauthorizedError()
        return found[1]


class FakeConnectorVerifier:
    """Connector tokens: token -> (server, actor)."""

    def __init__(self) -> None:
        self.tokens: dict[str, tuple[str, Actor]] = {}
        self.calls: list[tuple[str, str]] = []

    async def verify_connector(self, token: str, *, server: str) -> Actor:
        self.calls.append((token, server))
        found = self.tokens.get(token)
        if found is None or found[0] != server:
            raise UnauthorizedError()
        return found[1]


class RecordingAudit:
    """Keeps the audit events the MCP interface writes."""

    def __init__(self) -> None:
        self.events: list[AuditDraft] = []

    async def audit(self, event: AuditDraft) -> None:
        self.events.append(event)

    def of_type(self, event_type: str) -> list[AuditDraft]:
        return [e for e in self.events if e.type == event_type]


class FakeConnectorCourses:
    """ConnectorCoursesPort with a fixed answer per connector."""

    def __init__(self) -> None:
        self.by_connector: dict[UUID, frozenset[UUID] | None] = {}

    async def allowed_course_ids(self, connector_id: UUID) -> frozenset[UUID] | None:
        return self.by_connector.get(connector_id)


# - - - Academic - - -

LESSON_DATE = date(2026, 10, 7)
SUBJECT_ID = UUID(int=11)


def make_lesson(lesson_id: UUID | None = None, **changes: Any) -> LessonRef:
    """A scheduled lesson on 2026-10-07 with homework."""
    values: dict[str, Any] = {
        "id": lesson_id or new_id(),
        "date": LESSON_DATE,
        "period": 2,
        "starts_at": datetime(2026, 10, 7, 4, 0, tzinfo=UTC),
        "ends_at": datetime(2026, 10, 7, 5, 20, tzinfo=UTC),
        "subject_id": SUBJECT_ID,
        "subject_name": "Algebra",
        "teacher_id": UUID(int=21),
        "room_id": None,
        "room_slug": None,
        "room_name": "101",
        "audience": ("secret-group-key",),
        "group_names": ("2TN2",),
        "status": "scheduled",
        "topic": "Limits",
        "homework_text": "Exercises 1-5",
        "homework_due_date": date(2026, 10, 9),
    }
    values.update(changes)
    return LessonRef(**values)


class FakeSchedule:
    """ScheduleQueries subset."""

    def __init__(self) -> None:
        self.lessons: dict[UUID, LessonRef] = {}
        self.audience: set[tuple[UUID, UUID]] = set()  # (user_id, lesson_id)
        self.calls: list[tuple[str, tuple[Any, ...]]] = []

    async def projected_lessons_for_student(
        self, user_id: UUID, start: date, end: date
    ) -> list[LessonRef]:
        self.calls.append(("projected", (user_id, start, end)))
        return [
            lesson
            for lesson in self.lessons.values()
            if start <= lesson.date <= end and (user_id, lesson.id) in self.audience
        ]

    async def get_lesson(self, lesson_id: UUID) -> LessonRef | None:
        return self.lessons.get(lesson_id)

    async def is_in_audience(self, user_id: UUID, lesson_id: UUID) -> bool:
        return (user_id, lesson_id) in self.audience


class FakeClasswork:
    """ClassworkQueries subset."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...]]] = []
        self.lessons: list[LessonRef] = []
        self.homework_rows: list[dict[str, Any]] = []
        self.absence_rows: list[dict[str, Any]] = []

    async def subject_lessons(
        self,
        user_id: UUID,
        subject_id: UUID,
        start: date | None,
        end: date | None,
    ) -> list[LessonRef]:
        self.calls.append(("subject_lessons", (user_id, subject_id, start, end)))
        return self.lessons

    async def homework(
        self, user_id: UUID, start: date | None, end: date | None, done: bool | None
    ) -> list[dict[str, Any]]:
        self.calls.append(("homework", (user_id, start, end, done)))
        return self.homework_rows

    async def absences(
        self, user_id: UUID, start: date | None, end: date | None
    ) -> list[dict[str, Any]]:
        self.calls.append(("absences", (user_id, start, end)))
        return self.absence_rows


class FakeMarks:
    """MarksQueries subset."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...]]] = []

    async def subjects_summary(
        self, user_id: UUID, semester: int | None
    ) -> list[SubjectSummary]:
        self.calls.append(("subjects_summary", (user_id, semester)))
        return [
            SubjectSummary(
                subject_id=SUBJECT_ID,
                name="Algebra",
                teacher_names=("Aliev A.",),
                semester_mark=4.5,
                emis_rating=87,
                absences=1,
                lessons_with_attendance=20,
            )
        ]

    async def marks(
        self,
        user_id: UUID,
        subject_id: UUID | None,
        start: date | None,
        end: date | None,
    ) -> list[MarkRef]:
        self.calls.append(("marks", (user_id, subject_id, start, end)))
        return [
            MarkRef(
                subject_id=SUBJECT_ID,
                subject_name="Algebra",
                semester=3,
                type="lesson",
                value=5,
                date=LESSON_DATE,
                lesson_id=None,
            )
        ]

    async def results(self, user_id: UUID, semester: int | None) -> dict[str, Any]:
        self.calls.append(("results", (user_id, semester)))
        return {"semester": semester or 3, "gpa": 4.6, "subjects": []}


# - - - Files, links, flash cards - - -


def make_file(owner_id: UUID, **changes: Any) -> FileRef:
    """A ready PDF with 1 KB of text."""
    values: dict[str, Any] = {
        "id": new_id(),
        "owner_id": owner_id,
        "scope": FileScope.STUDENT,
        "purpose": FilePurpose.AI_UPLOAD,
        "name": "notes.pdf",
        "content_type": "application/pdf",
        "byte_size": 4096,
        "status": "ready",
        "text_bytes": 1024,
    }
    values.update(changes)
    return FileRef(**values)


class FakeFiles:
    """FilesApi subset plus list_owned."""

    def __init__(self) -> None:
        self.files: dict[UUID, FileRef] = {}
        self.pages: dict[UUID, list[str]] = {}
        self.searches: list[tuple[UUID, str, int]] = []

    def add(self, file: FileRef, pages: Sequence[str] = ("page one",)) -> FileRef:
        self.files[file.id] = file
        self.pages[file.id] = list(pages)
        return file

    async def transfer_ownership(
        self, file_ids: Sequence[UUID], new_owner_id: UUID
    ) -> None:
        """Record the moves (the fake keeps no quota)."""
        self.transferred: list[tuple[UUID, UUID]] = [
            *getattr(self, "transferred", []),
            *((file_id, new_owner_id) for file_id in file_ids),
        ]

    async def get(self, file_id: UUID) -> FileRef | None:
        return self.files.get(file_id)

    async def list_owned(self, owner_id: UUID, *, limit: int) -> list[FileRef]:
        owned = [f for f in self.files.values() if f.owner_id == owner_id]
        return owned[:limit]

    async def read_text_page(self, file_id: UUID, page: int) -> TextPage:
        pages = self.pages[file_id]
        if page > len(pages):
            raise NotFoundError()
        return TextPage(
            file_id=file_id, page=page, pages=len(pages), text=pages[page - 1]
        )

    async def search_text(
        self, owner_id: UUID, query: str, limit: int = 10
    ) -> list[dict[str, Any]]:
        self.searches.append((owner_id, query, limit))
        return [{"file_id": new_id(), "name": "notes.pdf", "snippet": query}]


def make_resource(lesson_id: UUID, **changes: Any) -> ResourceRef:
    """A material link of a lesson."""
    values: dict[str, Any] = {
        "link_id": new_id(),
        "lesson_id": lesson_id,
        "role": "material",
        "kind": "url",
        "short_url": "https://s.ihsu.uz/abc",
        "title": "Lecture slides",
        "author_id": UUID(int=21),
        "author_first_name": "Aliev",
        "hidden": False,
        "file_id": None,
    }
    values.update(changes)
    return ResourceRef(**values)


class FakeLinks:
    """LinksApi subset."""

    def __init__(self) -> None:
        self.resources: dict[UUID, list[ResourceRef]] = {}

    async def lesson_resources(
        self, lesson_id: UUID, *, include_hidden: bool = False
    ) -> list[ResourceRef]:
        return self.resources.get(lesson_id, [])


class FakeFlashcards:
    """FlashcardsApi with sets kept in a dict."""

    def __init__(self) -> None:
        self.sets: dict[UUID, dict[str, Any]] = {}
        self.owners: dict[UUID, UUID] = {}
        self.created: list[dict[str, Any]] = []
        self.added: list[tuple[UUID, UUID, list[tuple[str, str]]]] = []
        self.updated: list[tuple[UUID, UUID, str | None, str | None]] = []

    async def list_sets(self, owner_id: UUID) -> list[dict[str, Any]]:
        return [s for set_id, s in self.sets.items() if self.owners[set_id] == owner_id]

    async def get_set(
        self, set_id: UUID, owner_id: UUID | None
    ) -> dict[str, Any] | None:
        if self.owners.get(set_id) != owner_id:
            return None
        return self.sets[set_id]

    async def create_set(
        self,
        owner_id: UUID,
        title: str,
        cards: Sequence[tuple[str, str]],
        *,
        source: Literal["manual", "ai", "mcp", "copied"],
        source_chat_id: UUID | None = None,
        description: str | None = None,
    ) -> dict[str, Any]:
        set_id = new_id()
        record = {
            "id": set_id,
            "title": title,
            "source": source,
            "description": description,
            "card_count": len(cards),
        }
        self.sets[set_id] = record
        self.owners[set_id] = owner_id
        self.created.append({"owner_id": owner_id, "cards": list(cards), **record})
        return record

    async def add_cards(
        self, owner_id: UUID, set_id: UUID, cards: Sequence[tuple[str, str]]
    ) -> dict[str, Any]:
        self.added.append((owner_id, set_id, list(cards)))
        return {"id": set_id, "added": len(cards)}

    async def update_card(
        self, owner_id: UUID, card_id: UUID, front: str | None, back: str | None
    ) -> dict[str, Any]:
        self.updated.append((owner_id, card_id, front, back))
        return {"id": card_id, "front": front, "back": back}

    async def set_owner(self, set_id: UUID) -> UUID | None:
        return self.owners.get(set_id)


# - - - LMS and administration - - -


class FakeLmsQueries:
    """LmsQueries with canned answers; remembers what it was asked."""

    def __init__(self) -> None:
        self.courses: list[dict[str, Any]] = []
        self.steps: dict[UUID, dict[str, Any]] = {}
        self.calls: list[tuple[str, tuple[Any, ...]]] = []

    async def courses_for_staff(
        self, user_id: UUID, permission: str
    ) -> list[dict[str, Any]]:
        self.calls.append(("courses_for_staff", (user_id, permission)))
        return self.courses

    async def course_detail(self, course_id: UUID, actor: Actor) -> dict[str, Any]:
        self.calls.append(("course_detail", (course_id, actor)))
        return {"id": course_id, "title": "Calculus", "outline": []}

    async def step_draft(self, step_id: UUID, actor: Actor) -> dict[str, Any]:
        self.calls.append(("step_draft", (step_id, actor)))
        return self.steps[step_id]

    async def pending_changes(self, course_id: UUID, actor: Actor) -> dict[str, Any]:
        self.calls.append(("pending_changes", (course_id, actor)))
        return {"draft_seq": 4, "outline_changed": False, "steps": []}

    async def versions(self, course_id: UUID, actor: Actor) -> list[dict[str, Any]]:
        self.calls.append(("versions", (course_id, actor)))
        return [{"number": 1}]

    async def attempts(
        self, course_id: UUID, actor: Actor, limit: int = 50
    ) -> list[dict[str, Any]]:
        self.calls.append(("attempts", (course_id, limit)))
        return [{"id": "a1"}]


@dataclass
class LmsCall:
    """One call of the draft commands."""

    name: str
    actor: Actor
    args: tuple[Any, ...]
    via_mcp: bool = True


@dataclass
class FakeLmsCommands:
    """LmsDraftCommands recording every call."""

    calls: list[LmsCall] = field(default_factory=list)

    async def create_section(
        self, actor: Actor, course_id: UUID, title: str, *, via_mcp: bool
    ) -> dict[str, Any]:
        self.calls.append(LmsCall("create_section", actor, (course_id, title), via_mcp))
        return {"section_id": "s1", "title": title}

    async def create_step(
        self,
        actor: Actor,
        course_id: UUID,
        section_id: str,
        title: str,
        *,
        via_mcp: bool,
    ) -> dict[str, Any]:
        args = (course_id, section_id, title)
        self.calls.append(LmsCall("create_step", actor, args, via_mcp))
        return {"step_id": "st1", "title": title}

    async def create_course(
        self, actor: Actor, *, title: str, slug: str | None, visibility: str
    ) -> dict[str, Any]:
        self.calls.append(LmsCall("create_course", actor, (title, slug, visibility)))
        return {"id": "c1", "title": title, "visibility": visibility}

    async def update_course(
        self,
        actor: Actor,
        course_id: UUID,
        *,
        title: str | None,
        description: str | None,
    ) -> dict[str, Any]:
        self.calls.append(
            LmsCall("update_course", actor, (course_id, title, description))
        )
        return {"id": str(course_id), "title": title}

    async def delete_course(self, actor: Actor, course_id: UUID) -> dict[str, Any]:
        self.calls.append(LmsCall("delete_course", actor, (course_id,)))
        return {"course_id": str(course_id), "status": "archived"}

    async def update_module(
        self, actor: Actor, course_id: UUID, section_id: str, title: str
    ) -> dict[str, Any]:
        self.calls.append(
            LmsCall("update_module", actor, (course_id, section_id, title))
        )
        return {"id": str(course_id)}

    async def delete_module(
        self, actor: Actor, course_id: UUID, section_id: str
    ) -> dict[str, Any]:
        self.calls.append(LmsCall("delete_module", actor, (course_id, section_id)))
        return {"id": str(course_id)}

    async def update_step(
        self,
        actor: Actor,
        step_id: UUID,
        *,
        title: str | None,
        blocks: list[dict[str, Any]] | None,
    ) -> dict[str, Any]:
        self.calls.append(LmsCall("update_step", actor, (step_id, title, blocks)))
        return {"step_id": str(step_id)}

    async def delete_step(self, actor: Actor, step_id: UUID) -> dict[str, Any]:
        self.calls.append(LmsCall("delete_step", actor, (step_id,)))
        return {"step_id": str(step_id)}

    async def add_block(
        self, actor: Actor, step_id: UUID, block: dict[str, Any], *, via_mcp: bool
    ) -> dict[str, Any]:
        self.calls.append(LmsCall("add_block", actor, (step_id, block), via_mcp))
        return {"step_id": step_id, "blocks": [block]}

    async def add_question(
        self,
        actor: Actor,
        step_id: UUID,
        block_id: str,
        question: dict[str, Any],
        *,
        via_mcp: bool,
    ) -> dict[str, Any]:
        args = (step_id, block_id, question)
        self.calls.append(LmsCall("add_question", actor, args, via_mcp))
        return {"step_id": step_id, "question": question}


class FakeAdminTools:
    """AdminToolBackend recording (tool, arguments, actor)."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any], Actor]] = []

    async def call(
        self, tool: str, arguments: dict[str, Any], actor: Actor
    ) -> dict[str, Any]:
        self.calls.append((tool, arguments, actor))
        return {"tool": tool, "rows": []}
