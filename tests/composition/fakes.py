"""In-memory fakes of the contracts and local ports the composition endpoints use."""

import datetime as dt
from collections.abc import Sequence
from typing import Any, Literal
from uuid import UUID

from app.interfaces.http.v1.composition.ports import DayCounts, JsonObject
from app.shared.actor import Actor, Role
from app.shared.contracts.academic import (
    LessonRef,
    MarkRef,
    RoomRef,
    StudentRef,
    SubjectSummary,
)
from app.shared.contracts.identity import (
    TelegramAccountRef,
    UserPreferences,
    UserRef,
    UserStatus,
)
from app.shared.ids import new_id

UTC = dt.UTC
DEFAULT_LESSON_DAY = dt.date(2026, 10, 7)


def make_user(
    *roles: Role,
    user_id: UUID | None = None,
    first_name: str = "Aziza",
    last_name: str = "Karimova",
    status: UserStatus = UserStatus.ACTIVE,
    emis_status: Literal["active", "needs_reauth"] | None = "active",
) -> UserRef:
    """Build a user."""
    return UserRef(
        id=user_id or new_id(),
        login=f"{last_name}.{first_name}".lower(),
        first_name=first_name,
        last_name=last_name,
        middle_name=None,
        roles=frozenset(roles),
        status=status,
        locale="en",
        emis_status=emis_status,
    )


def make_lesson(
    *,
    day: dt.date = DEFAULT_LESSON_DAY,
    period: int = 1,
    subject: str = "Mathematics",
    teacher_id: UUID | None = None,
    room: str | None = "102",
    topic: str | None = None,
    homework: str | None = None,
    homework_due: dt.date | None = None,
    status: Literal["scheduled", "cancelled"] = "scheduled",
    group_id: UUID | None = None,
    group_name: str = "2TN2",
    subgroup: int | None = None,
    lesson_id: UUID | None = None,
) -> LessonRef:
    """Build a lesson starting at 08:30 Tashkent time (03:30 UTC) plus the period."""
    start = dt.datetime.combine(day, dt.time(3, 30), tzinfo=UTC) + dt.timedelta(
        minutes=55 * (period - 1)
    )
    key = str(group_id or new_id())
    label = group_name
    if subgroup is not None:
        key, label = f"{key}:{subgroup}", f"{group_name}/{subgroup}"
    return LessonRef(
        id=lesson_id or new_id(),
        date=day,
        period=period,
        starts_at=start,
        ends_at=start + dt.timedelta(minutes=45),
        subject_id=new_id(),
        subject_name=subject,
        teacher_id=teacher_id,
        room_id=new_id() if room else None,
        room_slug=room,
        room_name=room,
        audience=(key,),
        group_names=(label,),
        status=status,
        topic=topic,
        homework_text=homework,
        homework_due_date=homework_due,
    )


def make_student(
    user_id: UUID,
    *,
    subgroup: int | None = 1,
    group_name: str = "2TN2",
    status: Literal["active", "left"] = "active",
) -> StudentRef:
    """Build a student record."""
    return StudentRef(
        user_id=user_id,
        group_id=new_id(),
        group_name=group_name,
        subgroup=subgroup,
        status=status,
        synced_at=None,
    )


# - - - Contracts - - -


class FakeIdentity:
    """IdentityDirectory over a dictionary."""

    def __init__(self) -> None:
        """Start empty."""
        self.users: dict[UUID, UserRef] = {}
        self.get_users_calls: list[int] = []

    def add(self, user: UserRef) -> UserRef:
        """Add a user and return it."""
        self.users[user.id] = user
        return user

    async def get_user(self, user_id: UUID) -> UserRef | None:
        return self.users.get(user_id)

    async def get_users(self, user_ids: Sequence[UUID]) -> dict[UUID, UserRef]:
        self.get_users_calls.append(len(user_ids))
        return {uid: self.users[uid] for uid in user_ids if uid in self.users}

    async def get_preferences(self, user_id: UUID) -> UserPreferences:
        return UserPreferences()

    async def user_by_telegram(self, telegram_user_id: int) -> UserRef | None:
        return None

    async def user_by_login(self, login: str) -> UserRef | None:
        return None

    async def telegram_accounts(self, user_id: UUID) -> list[TelegramAccountRef]:
        return []

    async def user_ids_with_roles(self, roles: Sequence[Role]) -> list[UUID]:
        wanted = set(roles)
        return [u.id for u in self.users.values() if wanted & u.roles]

    async def search_users(
        self, query: str, *, roles: Sequence[Role] = (), limit: int = 20
    ) -> list[UserRef]:
        return []

    async def set_telegram_blocked(self, telegram_user_id: int, blocked: bool) -> None:
        return None

    async def touch_telegram(
        self, telegram_user_id: int, username: str | None, first_name: str
    ) -> None:
        return None


class FakeSchedule:
    """ScheduleQueries with canned data."""

    def __init__(self) -> None:
        """Start empty."""
        self.students: dict[UUID, StudentRef] = {}
        self.lessons: list[LessonRef] = []
        self.projected: list[LessonRef] = []
        self.group_users: dict[UUID, list[UUID]] = {}
        self.projected_calls: list[tuple[UUID, dt.date, dt.date]] = []
        self.search_calls: list[tuple[UUID, str, int]] = []

    async def get_student(self, user_id: UUID) -> StudentRef | None:
        return self.students.get(user_id)

    async def get_lesson(self, lesson_id: UUID) -> LessonRef | None:
        return next((x for x in self.lessons if x.id == lesson_id), None)

    async def lessons_for_student(
        self, user_id: UUID, start: dt.date, end: dt.date
    ) -> list[LessonRef]:
        return [x for x in self.lessons if start <= x.date <= end]

    async def lessons_for_teacher(
        self, teacher_id: UUID, start: dt.date, end: dt.date
    ) -> list[LessonRef]:
        return []

    async def is_in_audience(self, user_id: UUID, lesson_id: UUID) -> bool:
        return True

    async def is_lesson_teacher(self, user_id: UUID, lesson_id: UUID) -> bool:
        return False

    async def head_student_ids(self, lesson_id: UUID) -> list[UUID]:
        return []

    async def room_by_slug(self, slug: str) -> RoomRef | None:
        return None

    async def room_day(self, room_id: UUID, day: dt.date) -> list[LessonRef]:
        return []

    async def group_user_ids(
        self, group_ids: Sequence[UUID], semesters: Sequence[int] = ()
    ) -> list[UUID]:
        return [uid for gid in group_ids for uid in self.group_users.get(gid, [])]

    async def search_lessons(
        self, user_id: UUID, query: str, limit: int
    ) -> list[LessonRef]:
        self.search_calls.append((user_id, query, limit))
        needle = query.casefold()
        found = [x for x in self.lessons if needle in (x.topic or "").casefold()]
        return found[:limit]

    async def curated_group_ids(self, teacher_id: UUID) -> list[UUID]:
        return []

    async def projected_lessons_for_student(
        self, user_id: UUID, start: dt.date, end: dt.date
    ) -> list[LessonRef]:
        self.projected_calls.append((user_id, start, end))
        return [x for x in self.projected if start <= x.date <= end]


class FakeClasswork:
    """ClassworkQueries with canned data."""

    def __init__(self) -> None:
        """Start empty."""
        self.homework_entries: list[dict[str, Any]] = []
        self.missing: list[LessonRef] = []
        self.missing_calls: list[tuple[UUID | None, dt.date, dt.date]] = []

    async def subject_lessons(
        self,
        user_id: UUID,
        subject_id: UUID,
        start: dt.date | None,
        end: dt.date | None,
    ) -> list[LessonRef]:
        return []

    async def homework(
        self,
        user_id: UUID,
        start: dt.date | None,
        end: dt.date | None,
        done: bool | None,
    ) -> list[dict[str, Any]]:
        return list(self.homework_entries)

    async def absences(
        self, user_id: UUID, start: dt.date | None, end: dt.date | None
    ) -> list[dict[str, Any]]:
        return []

    async def missing_attendance(
        self, teacher_id: UUID | None, start: dt.date, end: dt.date
    ) -> list[LessonRef]:
        self.missing_calls.append((teacher_id, start, end))
        return list(self.missing)


class FakeMarks:
    """MarksQueries with canned data."""

    def __init__(self) -> None:
        """Start empty."""
        self.summaries: list[SubjectSummary] = []
        self.gpas: dict[UUID, float | None] = {}
        self.gpa_calls: list[list[UUID]] = []

    async def subjects_summary(
        self, user_id: UUID, semester: int | None
    ) -> list[SubjectSummary]:
        return list(self.summaries)

    async def marks(
        self,
        user_id: UUID,
        subject_id: UUID | None,
        start: dt.date | None,
        end: dt.date | None,
    ) -> list[MarkRef]:
        return []

    async def results(self, user_id: UUID, semester: int | None) -> dict[str, Any]:
        return {}

    async def new_marks_since(
        self, user_id: UUID, since: dt.datetime | None, limit: int = 20
    ) -> list[MarkRef]:
        return []

    async def gpa_for_users(
        self, user_ids: Sequence[UUID], semester: int | None
    ) -> dict[UUID, float | None]:
        self.gpa_calls.append(list(user_ids))
        return {uid: self.gpas.get(uid) for uid in user_ids}


class FakeAi:
    """AiQueries: a count of waiting approvals per user."""

    def __init__(self) -> None:
        """Start with no approvals."""
        self.pending: dict[UUID, int] = {}

    async def pending_approvals(self, user_id: UUID) -> int:
        return self.pending.get(user_id, 0)

    async def chat_for_share(
        self, chat_id: UUID, until_seq: int | None
    ) -> dict[str, Any] | None:
        return None

    async def chat_owner(self, chat_id: UUID) -> UUID | None:
        return None


class FakeFlashcards:
    """FlashcardsApi that only lists sets."""

    def __init__(self) -> None:
        """Start without sets."""
        self.sets: list[dict[str, Any]] = []
        self.list_calls = 0

    async def list_sets(self, owner_id: UUID) -> list[dict[str, Any]]:
        self.list_calls += 1
        return list(self.sets)

    async def get_set(
        self, set_id: UUID, owner_id: UUID | None
    ) -> dict[str, Any] | None:
        return None

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
        return {}

    async def add_cards(
        self, owner_id: UUID, set_id: UUID, cards: Sequence[tuple[str, str]]
    ) -> dict[str, Any]:
        return {}

    async def update_card(
        self, owner_id: UUID, card_id: UUID, front: str | None, back: str | None
    ) -> dict[str, Any]:
        return {}

    async def set_owner(self, set_id: UUID) -> UUID | None:
        return None


# - - - Local ports - - -


class FakeFiles:
    """FilesViews with canned data."""

    def __init__(self) -> None:
        """Start empty."""
        self.expiring: list[dt.date] = []
        self.found: list[JsonObject] = []
        self.until_calls: list[dt.date] = []
        self.search_calls: list[tuple[UUID, str, int]] = []

    async def expiry_dates(self, owner_id: UUID, until: dt.date) -> list[dt.date]:
        self.until_calls.append(until)
        return sorted(d for d in self.expiring if d <= until)

    async def search_files(
        self, owner_id: UUID, query: str, limit: int
    ) -> list[JsonObject]:
        self.search_calls.append((owner_id, query, limit))
        return list(self.found)


class FakeSync:
    """SyncViews with canned data."""

    def __init__(self) -> None:
        """Start healthy."""
        self.failures: dict[UUID, int] = {}
        self.last_run: JsonObject | None = None

    async def sync_failures(self, user_id: UUID) -> int:
        return self.failures.get(user_id, 0)

    async def last_sync_run(self, actor: Actor) -> JsonObject | None:
        return self.last_run


class FakeCalendarTokens:
    """CalendarTokenStore: token hash per student."""

    def __init__(self) -> None:
        """Start without tokens."""
        self.hashes: dict[UUID, str] = {}
        self.known_students: set[UUID] = set()
        self.lookups: list[str] = []

    async def rotate(self, user_id: UUID, token_hash: str) -> bool:
        if user_id not in self.known_students:
            return False
        self.hashes[user_id] = token_hash
        return True

    async def user_for_token(self, token_hash: str) -> UUID | None:
        self.lookups.append(token_hash)
        return next((uid for uid, h in self.hashes.items() if h == token_hash), None)


class FakeOverview:
    """ScheduleOverview with canned data."""

    def __init__(self) -> None:
        """Start with a term from 2026-09-02 to 2026-12-30."""
        self.bounds: tuple[dt.date, dt.date] | None = (
            dt.date(2026, 9, 2),
            dt.date(2026, 12, 30),
        )
        self.counts = DayCounts(lessons=0, cancelled=0, teacher_needed=0)
        self.group_ids: list[UUID] = []
        self.count_days: list[dt.date] = []

    async def term_bounds(self, day: dt.date) -> tuple[dt.date, dt.date] | None:
        return self.bounds

    async def day_counts(self, actor: Actor, day: dt.date) -> DayCounts:
        self.count_days.append(day)
        return self.counts

    async def active_group_ids(self) -> list[UUID]:
        return list(self.group_ids)


class FakeAttendance:
    """AttendanceStats with canned absence rates."""

    def __init__(self) -> None:
        """Start empty."""
        self.rates: dict[UUID, float | None] = {}
        self.calls: list[tuple[dt.date, dt.date]] = []

    async def group_absence_rates(
        self, actor: Actor, start: dt.date, end: dt.date
    ) -> dict[UUID, float | None]:
        self.calls.append((start, end))
        return dict(self.rates)


class FakeStudentViews:
    """StudentViews with canned pages."""

    def __init__(self) -> None:
        """Start with empty pages."""
        self.profile_data: JsonObject = {}
        self.timetable_data: list[JsonObject] = []
        self.grades_data: JsonObject = {}
        self.attendance_data: JsonObject = {}
        self.timetable_calls: list[tuple[UUID, dt.date, dt.date]] = []

    async def profile(self, user_id: UUID) -> JsonObject:
        return dict(self.profile_data)

    async def timetable(
        self, user_id: UUID, start: dt.date, end: dt.date
    ) -> list[JsonObject]:
        self.timetable_calls.append((user_id, start, end))
        return list(self.timetable_data)

    async def grades(self, user_id: UUID) -> JsonObject:
        return dict(self.grades_data)

    async def attendance(self, user_id: UUID) -> JsonObject:
        return dict(self.attendance_data)


class FakeTeacherViews:
    """TeacherViews with canned pages."""

    def __init__(self) -> None:
        """Start empty."""
        self.timetable_data: list[JsonObject] = []
        self.missing_data: list[JsonObject] = []
        self.groups_data: list[JsonObject] = []
        self.timetable_calls: list[tuple[UUID, dt.date, dt.date]] = []
        self.missing_calls: list[tuple[UUID, dt.date, dt.date]] = []

    async def timetable(
        self, teacher_id: UUID, start: dt.date, end: dt.date
    ) -> list[JsonObject]:
        self.timetable_calls.append((teacher_id, start, end))
        return list(self.timetable_data)

    async def missing_attendance(
        self, teacher_id: UUID, start: dt.date, end: dt.date
    ) -> list[JsonObject]:
        self.missing_calls.append((teacher_id, start, end))
        return list(self.missing_data)

    async def curated_groups(self, teacher_id: UUID) -> list[JsonObject]:
        return list(self.groups_data)


class FakeAccounts:
    """AccountViews that records who looked."""

    def __init__(self) -> None:
        """Start with an empty account."""
        self.detail: JsonObject = {}
        self.calls: list[tuple[UUID, UUID, str | None, str | None]] = []

    async def account(
        self, actor: Actor, user_id: UUID, *, ip: str | None, user_agent: str | None
    ) -> JsonObject:
        self.calls.append((actor.user_id, user_id, ip, user_agent))
        return dict(self.detail)


class FakeBroadcasts:
    """BroadcastViews with canned items."""

    def __init__(self) -> None:
        """Start empty."""
        self.items: list[JsonObject] = []
        self.limits: list[int] = []

    async def scheduled(self, actor: Actor, limit: int) -> list[JsonObject]:
        self.limits.append(limit)
        return list(self.items)
