"""In-memory fakes of the contracts the bot consumes (only what it calls)."""

import copy
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from typing import Any, Literal
from uuid import UUID

from app.settings import Settings
from app.shared.actor import Actor, Role
from app.shared.contracts.academic import (
    LessonRef,
    MarkRef,
    SubjectSummary,
)
from app.shared.contracts.files import FilePurpose, FileRef, FileScope
from app.shared.contracts.identity import (
    TelegramAccountRef,
    UserPreferences,
    UserRef,
    UserStatus,
)
from app.shared.contracts.links import ResourceRef
from app.shared.contracts.mail import MailSummary
from app.shared.ids import new_id
from tests.bot.support.i18n import KeyI18nCore
from tests.fakes.clock import FixedClock

NOW = datetime(2026, 10, 6, 9, 0, tzinfo=UTC)
TODAY = date(2026, 10, 6)
STUDENT_TG = 1001
TEACHER_TG = 2002
ADMIN_CHAT = 555


def make_user(
    *roles: Role,
    login: str = "brastilov.aleksey",
    locale: str = "en",
    status: UserStatus = UserStatus.ACTIVE,
) -> UserRef:
    """A user with the given roles."""
    return UserRef(
        id=new_id(),
        login=login,
        first_name="Aleksey",
        last_name="Brastilov",
        middle_name=None,
        roles=frozenset(roles),
        status=status,
        locale=locale,
        emis_status=None,
    )


def make_lesson(**overrides: Any) -> LessonRef:
    """A lesson that ends 5 minutes after NOW (the prompt moment)."""
    values: dict[str, Any] = {
        "id": new_id(),
        "date": TODAY,
        "period": 3,
        "starts_at": NOW - timedelta(minutes=40),
        "ends_at": NOW + timedelta(minutes=5),
        "subject_id": new_id(),
        "subject_name": "Physics",
        "teacher_id": None,
        "room_id": new_id(),
        "room_slug": "102",
        "room_name": "Room 102",
        "audience": (),
        "group_names": ("2TN2",),
        "status": "scheduled",
        "topic": None,
        "homework_text": None,
        "homework_due_date": None,
    }
    values.update(overrides)
    return LessonRef(**values)


def make_mail(subject: str = "Hello", **overrides: Any) -> MailSummary:
    """An incoming email summary."""
    values: dict[str, Any] = {
        "id": new_id(),
        "direction": "in",
        "from_address": "teacher@example.com",
        "to": ("brastilov.aleksey@mail.ihsu.uz",),
        "subject": subject,
        "snippet": "snippet",
        "occurred_at": NOW - timedelta(hours=1),
        "purged": False,
    }
    values.update(overrides)
    return MailSummary(**values)


def make_file_ref(name: str, size: int, owner_id: UUID | None = None) -> FileRef:
    """A mail attachment."""
    return FileRef(
        id=new_id(),
        owner_id=owner_id or new_id(),
        scope=FileScope.MAIL,
        purpose=FilePurpose.MAIL,
        name=name,
        content_type="application/octet-stream",
        byte_size=size,
        status="ready",
        text_bytes=None,
    )


class FakeDirectory:
    """IdentityDirectory: users by Telegram id, accounts and preferences."""

    def __init__(self) -> None:
        """Start empty."""
        self.users: dict[int, UserRef] = {}
        self.accounts: dict[int, TelegramAccountRef] = {}
        self.preferences: dict[UUID, UserPreferences] = {}
        self.blocked_calls: list[tuple[int, bool]] = []
        self.touch_calls: list[tuple[int, str | None, str]] = []

    def link(
        self, telegram_id: int, user: UserRef, *, username: str | None = None
    ) -> None:
        """Link a Telegram account to a user."""
        self.users[telegram_id] = user
        self.accounts[telegram_id] = TelegramAccountRef(
            telegram_user_id=telegram_id,
            user_id=user.id,
            otp_delivery=True,
            username=username,
            blocked=False,
        )

    async def user_by_telegram(self, telegram_user_id: int) -> UserRef | None:
        """Return the linked user."""
        return self.users.get(telegram_user_id)

    async def telegram_accounts(self, user_id: UUID) -> list[TelegramAccountRef]:
        """Return the user's accounts."""
        return [a for a in self.accounts.values() if a.user_id == user_id]

    async def get_preferences(self, user_id: UUID) -> UserPreferences:
        """Return stored preferences or defaults."""
        return self.preferences.get(user_id, UserPreferences())

    async def photo_urls(self, user_ids: Sequence[UUID]) -> dict[UUID, str]:
        """No user has a photo in this fake."""
        return {}

    async def set_telegram_blocked(self, telegram_user_id: int, blocked: bool) -> None:
        """Record the call and update the account."""
        self.blocked_calls.append((telegram_user_id, blocked))
        account = self.accounts.get(telegram_user_id)
        if account is not None:
            self.accounts[telegram_user_id] = replace(account, blocked=blocked)

    async def touch_telegram(
        self, telegram_user_id: int, username: str | None, first_name: str
    ) -> None:
        """Record the call and update the username."""
        self.touch_calls.append((telegram_user_id, username, first_name))
        account = self.accounts.get(telegram_user_id)
        if account is not None:
            self.accounts[telegram_user_id] = replace(account, username=username)


class FakeIdentityCommands:
    """IdentityCommands: preference updates and unlinking."""

    def __init__(self, directory: FakeDirectory) -> None:
        """Share state with the directory."""
        self.directory = directory
        self.patches: list[dict[str, Any]] = []
        self.unlinked: list[int] = []

    async def update_preferences(
        self, user_id: UUID, patch: dict[str, Any]
    ) -> UserPreferences:
        """Merge the patch like the real implementation."""
        self.patches.append(patch)
        current = await self.directory.get_preferences(user_id)
        merged = UserPreferences.model_validate({**current.model_dump(), **patch})
        self.directory.preferences[user_id] = merged
        return merged

    async def unlink_telegram(self, telegram_user_id: int) -> None:
        """Remove the link."""
        self.unlinked.append(telegram_user_id)
        self.directory.users.pop(telegram_user_id, None)
        self.directory.accounts.pop(telegram_user_id, None)


class FakeCancelOtpReset:
    """The identity use case cancel_otp_reset."""

    def __init__(self) -> None:
        """No calls yet."""
        self.requests: list[UUID] = []

    async def execute(self, request_id: UUID) -> None:
        """Record the request id."""
        self.requests.append(request_id)


class FakeSchedule:
    """ScheduleQueries: the lessons returned for any range."""

    def __init__(self) -> None:
        """No lessons and no failure."""
        self.student_lessons: list[LessonRef] = []
        self.teacher_lessons: list[LessonRef] = []
        self.error: Exception | None = None  # raised by lessons_for_student

    async def lessons_for_student(
        self, user_id: UUID, start: date, end: date
    ) -> list[LessonRef]:
        """Return the configured student lessons (or raise the configured error)."""
        if self.error is not None:
            raise self.error
        return list(self.student_lessons)

    async def lessons_for_teacher(
        self, teacher_id: UUID, start: date, end: date
    ) -> list[LessonRef]:
        """Return the configured teacher lessons."""
        return list(self.teacher_lessons)


class FakeClassworkQueries:
    """ClassworkQueries: homework items and lessons missing attendance."""

    def __init__(self) -> None:
        """Nothing to do."""
        self.items: list[dict[str, Any]] = []
        self.missing: list[LessonRef] = []
        self.homework_starts: list[date | None] = []

    async def homework(
        self, user_id: UUID, start: date | None, end: date | None, done: bool | None
    ) -> list[dict[str, Any]]:
        """Return items filtered by the done flag; remember the lower bound asked."""
        self.homework_starts.append(start)
        return [i for i in self.items if done is None or bool(i["done_at"]) == done]

    async def missing_attendance(
        self, teacher_id: UUID | None, start: date, end: date
    ) -> list[LessonRef]:
        """Return lessons without attendance."""
        return list(self.missing)


@dataclass
class FakeClasswork:
    """ClassworkCommands over an in-memory prompt state."""

    state: dict[str, Any]
    calls: list[tuple[str, Any]] = field(default_factory=list)
    prompt_error: Exception | None = None
    submit_error: Exception | None = None

    @classmethod
    def with_roster(cls, lesson: LessonRef, names: list[str]) -> "FakeClasswork":
        """A prompt for the lesson with these students (position = index)."""
        roster = [
            {
                "position": index,
                "user_id": new_id(),
                "name": name,
                "group_name": "2TN2",
                "subgroup_unset": False,
                "absent": False,
            }
            for index, name in enumerate(names)
        ]
        return cls(
            state={
                "lesson": lesson,
                "roster": roster,
                "attendance_submitted": False,
                "attendance_version": 3,
                "homework_text": None,
                "expired": False,
            }
        )

    @property
    def lesson(self) -> LessonRef:
        """The lesson of the prompt."""
        lesson: LessonRef = self.state["lesson"]
        return lesson

    def _snapshot(self) -> dict[str, Any]:
        return copy.deepcopy(self.state)

    async def prompt_state(self, lesson_id: UUID, teacher_id: UUID) -> dict[str, Any]:
        """Return the state (or raise the configured error)."""
        self.calls.append(("prompt_state", lesson_id))
        if self.prompt_error is not None:
            raise self.prompt_error
        return self._snapshot()

    async def toggle_draft_absent(
        self, lesson_id: UUID, teacher_id: UUID, position: int
    ) -> dict[str, Any]:
        """Flip the student at the position."""
        self.calls.append(("toggle", position))
        item = self.state["roster"][position]
        item["absent"] = not item["absent"]
        return self._snapshot()

    async def submit_attendance(
        self,
        lesson_id: UUID,
        actor: Actor,
        *,
        absent: list[UUID] | None,
        from_draft: bool,
        base_version: int,
        source: Literal["bot", "staff", "admin"],
    ) -> dict[str, Any]:
        """Record the submission and mark attendance as submitted."""
        self.calls.append(
            (
                "submit",
                {
                    "absent": absent,
                    "from_draft": from_draft,
                    "base_version": base_version,
                    "source": source,
                },
            )
        )
        if self.submit_error is not None:
            error, self.submit_error = self.submit_error, None
            raise error
        if not from_draft:
            for item in self.state["roster"]:
                item["absent"] = item["user_id"] in (absent or [])
        self.state["attendance_submitted"] = True
        return self._snapshot()

    async def set_homework(
        self, lesson_id: UUID, actor: Actor, text: str, due_date: date | None
    ) -> LessonRef:
        """Store the homework."""
        self.calls.append(("set_homework", text))
        self.state["homework_text"] = text
        return self.lesson

    async def clear_homework(self, lesson_id: UUID, actor: Actor) -> None:
        """Remove the homework."""
        self.calls.append(("clear_homework", lesson_id))
        self.state["homework_text"] = None

    async def set_topic(self, lesson_id: UUID, actor: Actor, topic: str) -> LessonRef:
        """Store the topic."""
        self.calls.append(("set_topic", topic))
        return self.lesson

    async def set_homework_done(
        self, lesson_id: UUID, actor: Actor, done: bool
    ) -> None:
        """Record the tick."""
        self.calls.append(("homework_done", (lesson_id, done)))


class FakeMarks:
    """MarksQueries: marks, results and subjects."""

    def __init__(self) -> None:
        """No marks."""
        self.mark_list: list[MarkRef] = []
        self.result: dict[str, Any] = {"semester": 1, "gpa": None, "subjects": []}
        self.subjects: list[SubjectSummary] = []

    async def marks(
        self,
        user_id: UUID,
        subject_id: UUID | None,
        start: date | None,
        end: date | None,
    ) -> list[MarkRef]:
        """Return the configured marks."""
        return list(self.mark_list)

    async def results(self, user_id: UUID, semester: int | None) -> dict[str, Any]:
        """Return the configured results."""
        return self.result

    async def subjects_summary(
        self, user_id: UUID, semester: int | None
    ) -> list[SubjectSummary]:
        """Return the configured subjects."""
        return list(self.subjects)


class FakeLinks:
    """LinksApi: add_lesson_resource."""

    def __init__(self) -> None:
        """No resources yet."""
        self.added: list[dict[str, Any]] = []

    async def add_lesson_resource(
        self,
        actor: Actor,
        lesson_id: UUID,
        *,
        role: Literal["material", "attachment"],
        url: str | None = None,
        file_id: UUID | None = None,
    ) -> ResourceRef:
        """Record the call and return a short link."""
        self.added.append(
            {"lesson_id": lesson_id, "role": role, "url": url, "file_id": file_id}
        )
        return ResourceRef(
            link_id=new_id(),
            lesson_id=lesson_id,
            role=role,
            kind="file" if file_id else "url",
            short_url="https://s.ihsu.uz/abc123",
            title="lecture.pdf" if file_id else (url or ""),
            author_id=actor.user_id,
            author_first_name="Aleksey",
            hidden=False,
            file_id=file_id,
        )


class FakeFiles:
    """FilesApi: store_bytes and read_bytes."""

    def __init__(self) -> None:
        """No files yet."""
        self.stored: list[dict[str, Any]] = []
        self.contents: dict[UUID, bytes] = {}

    async def transfer_ownership(
        self, file_ids: Sequence[UUID], new_owner_id: UUID
    ) -> None:
        """Record the moves (the fake keeps no quota)."""
        self.transferred: list[tuple[UUID, UUID]] = [
            *getattr(self, "transferred", []),
            *((file_id, new_owner_id) for file_id in file_ids),
        ]

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
        """Remember the upload and return its reference."""
        ref = FileRef(
            id=new_id(),
            owner_id=owner_id,
            scope=scope,
            purpose=purpose,
            name=name,
            content_type="application/pdf",
            byte_size=len(data),
            status="ready",
            text_bytes=None,
        )
        self.stored.append({"ref": ref, "data": data})
        self.contents[ref.id] = data
        return ref

    async def read_bytes(self, file_id: UUID) -> bytes:
        """Return the stored bytes."""
        return self.contents[file_id]


class FakeMail:
    """MailApi: list, view and the sending operations."""

    def __init__(self) -> None:
        """An empty mailbox."""
        self.mails: list[MailSummary] = []
        self.views: dict[UUID, dict[str, Any]] = {}
        self.sent: list[dict[str, Any]] = []
        self.replies: list[dict[str, Any]] = []
        self.forwards: list[dict[str, Any]] = []
        self.spam_calls: list[tuple[UUID, bool]] = []
        self.recent_calls: list[dict[str, Any]] = []

    def add(self, summary: MailSummary, **view: Any) -> MailSummary:
        """Add an email with a view (body defaults to a short text)."""
        self.mails.append(summary)
        self.views[summary.id] = {
            "summary": summary,
            "text": view.get("text", "full text"),
            "html_telegram": view.get("html_telegram", "<b>body</b>"),
            "attachments": view.get("attachments", []),
            "truncated": view.get("truncated", False),
        }
        return summary

    def address_of(self, login: str) -> str:
        """The mail address of a login."""
        return f"{login}@mail.ihsu.uz"

    async def recent(
        self, user_id: UUID, *, limit: int = 10, before: datetime | None = None
    ) -> list[MailSummary]:
        """Return the newest emails before the cutoff."""
        self.recent_calls.append({"limit": limit, "before": before})
        found = [m for m in self.mails if before is None or m.occurred_at < before]
        return sorted(found, key=lambda m: m.occurred_at, reverse=True)[:limit]

    async def view(self, user_id: UUID, mail_id: UUID) -> dict[str, Any]:
        """Return the stored view."""
        return self.views[mail_id]

    async def send(
        self, user_id: UUID, *, to: list[str], subject: str, html: str
    ) -> MailSummary:
        """Record the new email."""
        self.sent.append({"to": list(to), "subject": subject, "html": html})
        return make_mail(subject, direction="out")

    async def reply(self, user_id: UUID, mail_id: UUID, *, html: str) -> MailSummary:
        """Record the reply."""
        self.replies.append({"mail_id": mail_id, "html": html})
        return make_mail("Re", direction="out")

    async def forward(
        self,
        user_id: UUID,
        mail_id: UUID,
        *,
        to: list[str],
        note_html: str | None,
    ) -> MailSummary:
        """Record the forward."""
        self.forwards.append({"mail_id": mail_id, "to": list(to), "note": note_html})
        return make_mail("Fwd", direction="out")

    async def mark_spam(self, user_id: UUID, mail_id: UUID, *, spam: bool) -> None:
        """Record the spam mark."""
        self.spam_calls.append((mail_id, spam))


class FakeNotify:
    """NotifyApi: the unread counter."""

    def __init__(self) -> None:
        """Nothing unread."""
        self.unread = 0

    async def unread_count(self, user_id: UUID) -> int:
        """Return the configured count."""
        return self.unread


@dataclass
class World:
    """Everything a bot test needs: the container, the fakes and two users."""

    container: SimpleNamespace
    clock: FixedClock
    student: UserRef
    teacher: UserRef
    directory: FakeDirectory
    identity_commands: FakeIdentityCommands
    cancel_otp: FakeCancelOtpReset
    schedule: FakeSchedule
    classwork_queries: FakeClassworkQueries
    marks: FakeMarks
    links: FakeLinks
    files: FakeFiles
    mail: FakeMail
    notify: FakeNotify
    i18n: KeyI18nCore
    classwork: FakeClasswork = field(init=False)

    def use_classwork(self, classwork: FakeClasswork) -> FakeClasswork:
        """Install the classwork fake in the container."""
        self.classwork = classwork
        self.container.academic.classwork.commands = classwork
        return classwork


def build_world() -> World:
    """Build the container of fakes with a linked student and a linked teacher."""
    student = make_user(Role.STUDENT)
    teacher = make_user(Role.TEACHER, login="ivanova.maria")
    directory = FakeDirectory()
    directory.link(STUDENT_TG, student, username="student")
    directory.link(TEACHER_TG, teacher, username="teacher")
    identity_commands = FakeIdentityCommands(directory)
    cancel_otp = FakeCancelOtpReset()
    schedule, queries = FakeSchedule(), FakeClassworkQueries()
    marks, links, files = FakeMarks(), FakeLinks(), FakeFiles()
    mail, notify = FakeMail(), FakeNotify()
    clock = FixedClock(NOW)
    i18n = KeyI18nCore()
    container = SimpleNamespace(
        settings=Settings(env="test", telegram={"admin_chat_id": ADMIN_CHAT}),
        clock=clock,
        redis=None,
        i18n=i18n,
        identity=SimpleNamespace(
            directory=directory,
            commands=identity_commands,
            auth=SimpleNamespace(cancel_otp_reset=cancel_otp),
        ),
        academic=SimpleNamespace(
            schedule=SimpleNamespace(queries=schedule),
            classwork=SimpleNamespace(queries=queries, commands=None),
            marks=SimpleNamespace(queries=marks),
        ),
        links=SimpleNamespace(public=links),
        files=SimpleNamespace(public=files),
        mail=SimpleNamespace(public=mail),
        notify=SimpleNamespace(public=notify),
    )
    world = World(
        container=container,
        clock=clock,
        student=student,
        teacher=teacher,
        directory=directory,
        identity_commands=identity_commands,
        cancel_otp=cancel_otp,
        schedule=schedule,
        classwork_queries=queries,
        marks=marks,
        links=links,
        files=files,
        mail=mail,
        notify=notify,
        i18n=i18n,
    )
    lesson = make_lesson(teacher_id=teacher.id)
    world.use_classwork(FakeClasswork.with_roster(lesson, ["Alice", "Bob", "Carol"]))
    return world
