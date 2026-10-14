"""Fakes of the other modules' contracts that the assistants consume."""

import asyncio
import datetime as dt
from collections.abc import Sequence
from typing import Any, Literal
from uuid import UUID

from app.shared.actor import Actor, Role
from app.shared.base_error import BaseError
from app.shared.contracts.academic import LessonRef, MarkRef, SubjectSummary
from app.shared.contracts.files import FilePurpose, FileRef, FileScope, TextPage
from app.shared.contracts.identity import UserRef, UserStatus
from app.shared.contracts.links import ResourceRef
from app.shared.ids import new_id

# - - - Factories - - -

DEFAULT_DAY = dt.date(2026, 10, 7)


def make_user(
    *roles: Role, first: str = "Aziza", last: str = "Karimova", locale: str = "en"
) -> UserRef:
    """A user with the given roles."""
    return UserRef(
        id=new_id(),
        login=f"{last.lower()}.{first.lower()}",
        first_name=first,
        last_name=last,
        middle_name=None,
        roles=frozenset(roles or {Role.STUDENT}),
        status=UserStatus.ACTIVE,
        locale=locale,
        emis_status="active",
    )


def make_lesson(
    *,
    subject: str = "Physics",
    subject_id: UUID | None = None,
    day: dt.date = DEFAULT_DAY,
    period: int = 2,
    homework: str | None = None,
) -> LessonRef:
    """A scheduled lesson."""
    start = dt.datetime(day.year, day.month, day.day, 5, 0, tzinfo=dt.UTC)
    return LessonRef(
        id=new_id(),
        date=day,
        period=period,
        starts_at=start,
        ends_at=start + dt.timedelta(minutes=80),
        subject_id=subject_id or new_id(),
        subject_name=subject,
        teacher_id=None,
        room_id=None,
        room_slug=None,
        room_name="102",
        audience=(),
        group_names=("2TN2",),
        status="scheduled",
        topic="Waves",
        homework_text=homework,
        homework_due_date=None,
    )


def make_file(
    owner_id: UUID,
    *,
    name: str = "notes.pdf",
    text_bytes: int | None = 2000,
    status: str = "ready",
) -> FileRef:
    """A stored file."""
    return FileRef(
        id=new_id(),
        owner_id=owner_id,
        scope=FileScope.STUDENT,
        purpose=FilePurpose.AI_UPLOAD,
        name=name,
        content_type="application/pdf",
        byte_size=5000,
        status=status,
        text_bytes=text_bytes,
    )


# - - - Fakes - - -


class FakeIdentity:
    """IdentityDirectory with a few users."""

    def __init__(self, *users: UserRef) -> None:
        """Index the users."""
        self.users = {u.id: u for u in users}

    async def get_user(self, user_id: UUID) -> UserRef | None:
        """Return the user."""
        return self.users.get(user_id)

    async def get_users(self, user_ids: Sequence[UUID]) -> dict[UUID, UserRef]:
        """Return the known users."""
        return {u: self.users[u] for u in user_ids if u in self.users}


class FakeMarks:
    """MarksQueries with canned data and a call log."""

    def __init__(self) -> None:
        """Start empty."""
        self.summary: list[SubjectSummary] = []
        self.rows: list[MarkRef] = []
        self.calls: list[tuple[str, tuple[Any, ...]]] = []

    async def subjects_summary(
        self, user_id: UUID, semester: int | None
    ) -> list[SubjectSummary]:
        """Return the canned summary."""
        self.calls.append(("subjects_summary", (user_id, semester)))
        return self.summary

    async def marks(
        self,
        user_id: UUID,
        subject_id: UUID | None,
        start: dt.date | None,
        end: dt.date | None,
    ) -> list[MarkRef]:
        """Return canned marks of the subject."""
        self.calls.append(("marks", (user_id, subject_id, start, end)))
        return [m for m in self.rows if subject_id in (None, m.subject_id)]


class FakeClasswork:
    """ClassworkQueries with canned data."""

    def __init__(self) -> None:
        """Start empty."""
        self.lessons: list[LessonRef] = []
        self.homework_rows: list[dict[str, Any]] = []
        self.absence_rows: list[dict[str, Any]] = []
        self.calls: list[tuple[str, tuple[Any, ...]]] = []

    async def subject_lessons(
        self,
        user_id: UUID,
        subject_id: UUID,
        start: dt.date | None,
        end: dt.date | None,
    ) -> list[LessonRef]:
        """Return the lessons of the subject."""
        self.calls.append(("subject_lessons", (user_id, subject_id, start, end)))
        return [x for x in self.lessons if x.subject_id == subject_id]

    async def homework(
        self,
        user_id: UUID,
        start: dt.date | None,
        end: dt.date | None,
        done: bool | None,
    ) -> list[dict[str, Any]]:
        """Return the homework rows."""
        self.calls.append(("homework", (user_id, start, end, done)))
        return self.homework_rows

    async def absences(
        self, user_id: UUID, start: dt.date | None, end: dt.date | None
    ) -> list[dict[str, Any]]:
        """Return the absence rows."""
        self.calls.append(("absences", (user_id, start, end)))
        return self.absence_rows


class FakeSchedule:
    """ScheduleQueries: audience and projected lessons."""

    def __init__(self) -> None:
        """Start with no audience."""
        self.audience: set[tuple[UUID, UUID]] = set()
        self.lessons: list[LessonRef] = []

    async def is_in_audience(self, user_id: UUID, lesson_id: UUID) -> bool:
        """Return True if the pair was registered."""
        return (user_id, lesson_id) in self.audience

    async def projected_lessons_for_student(
        self, user_id: UUID, start: dt.date, end: dt.date
    ) -> list[LessonRef]:
        """Return the lessons inside the range."""
        return [x for x in self.lessons if start <= x.date <= end]

    async def subject_emis_id(self, subject_id: UUID) -> int | None:
        """No subject has an EMIS id in these fakes."""
        return None

    async def subject_title(self, subject_id: UUID) -> str | None:
        """The name of the subject from any lesson of it; None when there is none."""
        names = (x.subject_name for x in self.lessons if x.subject_id == subject_id)
        return next(names, None)


class FakeFiles:
    """FilesApi with files owned by users; check_access = ownership."""

    def __init__(self) -> None:
        """Start empty."""
        self.files: dict[UUID, FileRef] = {}
        self.pages: dict[UUID, list[str]] = {}
        self.stored: dict[UUID, bytes] = {}

    def add(self, ref: FileRef, *pages: str) -> FileRef:
        """Register a file and its text pages."""
        self.files[ref.id] = ref
        self.pages[ref.id] = list(pages) or ["page one"]
        return ref

    async def get(self, file_id: UUID) -> FileRef | None:
        """Return the file."""
        return self.files.get(file_id)

    async def get_many(self, file_ids: Sequence[UUID]) -> dict[UUID, FileRef]:
        """Return the known files."""
        return {f: self.files[f] for f in file_ids if f in self.files}

    async def store_bytes(
        self,
        *,
        owner_id: UUID,
        scope: FileScope,
        purpose: FilePurpose,
        name: str,
        data: bytes,
        expires_days: int | None = None,
    ) -> FileRef:
        """Keep the bytes next to the registered ref."""
        ref = FileRef(
            id=new_id(),
            owner_id=owner_id,
            scope=scope,
            purpose=purpose,
            name=name,
            content_type="application/octet-stream",
            byte_size=len(data),
            status="ready",
            text_bytes=None,
        )
        self.files[ref.id] = ref
        self.stored[ref.id] = data
        return ref

    async def check_access(self, file_id: UUID, actor: Actor) -> bool:
        """Only the owner has access."""
        ref = self.files.get(file_id)
        return ref is not None and ref.owner_id == actor.user_id

    async def read_text_page(self, file_id: UUID, page: int) -> TextPage:
        """Return a page (1-based) of the registered text."""
        pages = self.pages[file_id]
        return TextPage(
            file_id=file_id, page=page, pages=len(pages), text=pages[page - 1]
        )

    async def search_text(
        self, owner_id: UUID, query: str, limit: int = 10
    ) -> list[dict[str, Any]]:
        """Return the owner's files whose name contains the query."""
        return [
            {"file_id": str(f.id), "name": f.name}
            for f in self.files.values()
            if f.owner_id == owner_id and query.lower() in f.name.lower()
        ][:limit]


class FakeFlashcards:
    """FlashcardsApi in memory."""

    def __init__(self) -> None:
        """Start empty."""
        self.sets: dict[UUID, dict[str, Any]] = {}
        self.create_calls: list[dict[str, Any]] = []
        self.delay = 0.0  # lets tests interleave coroutines during a write

    async def list_sets(self, owner_id: UUID) -> list[dict[str, Any]]:
        """Return the owner's sets."""
        return [s for s in self.sets.values() if s["owner_id"] == owner_id]

    async def get_set(
        self, set_id: UUID, owner_id: UUID | None
    ) -> dict[str, Any] | None:
        """Return a set of the owner."""
        found = self.sets.get(set_id)
        if found is None or (owner_id is not None and found["owner_id"] != owner_id):
            return None
        return found

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
        """Create a set."""
        await asyncio.sleep(self.delay)
        created = {
            "id": new_id(),
            "owner_id": owner_id,
            "title": title,
            "card_count": len(cards),
            "cards": list(cards),
        }
        self.sets[created["id"]] = created
        self.create_calls.append(
            {
                "title": title,
                "source": source,
                "chat_id": source_chat_id,
                "cards": list(cards),
            }
        )
        return created

    async def add_cards(
        self, owner_id: UUID, set_id: UUID, cards: Sequence[tuple[str, str]]
    ) -> dict[str, Any]:
        """Append cards to a set."""
        found = self.sets[set_id]
        found["cards"].extend(cards)
        found["card_count"] = len(found["cards"])
        return found


class FakeLinks:
    """LinksApi.lesson_resources with canned resources."""

    def __init__(self) -> None:
        """Start empty."""
        self.items: dict[UUID, list[ResourceRef]] = {}

    async def lesson_resources(
        self, lesson_id: UUID, *, include_hidden: bool = False
    ) -> list[ResourceRef]:
        """Return the lesson's resources."""
        return self.items.get(lesson_id, [])


class FakeAdminBackend:
    """AdminToolBackend that records calls and can fail."""

    def __init__(self) -> None:
        """Start with no calls."""
        self.calls: list[tuple[str, dict[str, Any], Actor]] = []
        self.results: dict[str, dict[str, Any]] = {}
        self.fail_with: BaseError | None = None

    async def call(
        self, tool: str, arguments: dict[str, Any], actor: Actor
    ) -> dict[str, Any]:
        """Record the call and return the canned result."""
        self.calls.append((tool, arguments, actor))
        if self.fail_with is not None:
            raise self.fail_with
        return self.results.get(tool, {"ok": True})
