"""The test environment: the schedule services on fakes or on PostgreSQL."""

import datetime as dt
from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID

from app.modules.academic.application.schedule.common import UowFactory
from app.modules.academic.application.schedule.ports.reader import ScheduleReader
from app.modules.academic.domain.schedule.group import Group
from app.modules.academic.domain.schedule.lesson import Lesson
from app.modules.academic.domain.schedule.room import Room
from app.modules.academic.domain.schedule.student import Student
from app.modules.academic.domain.schedule.subject import Subject
from app.modules.academic.domain.schedule.term import Bell, MovedDay, Term
from app.modules.academic.domain.schedule.timetable_entry import (
    EntrySource,
    TimetableEntry,
    WeekParity,
)
from app.modules.academic.infrastructure.orm import Lesson as LessonRow
from app.modules.academic.infrastructure.orm import Mark as MarkRow
from app.modules.academic.infrastructure.schedule.import_store import RedisImportStore
from app.modules.academic.infrastructure.schedule.mappers import lesson_to_entity
from app.modules.academic.infrastructure.schedule.reader import SqlScheduleReader
from app.modules.academic.infrastructure.schedule.uow import SqlScheduleUnitOfWork
from app.modules.academic.wiring_emis_import import (
    EmisImportServices,
    assemble_emis_import,
)
from app.modules.academic.wiring_schedule import ScheduleServices, assemble_schedule
from app.shared.actor import Role
from app.shared.contracts.identity import UserRef, UserStatus
from app.shared.ids import new_id, random_digits
from app.shared.lesson_kind import LessonKind
from app.shared.notifications import AuditDraft, NotificationDraft
from app.shared.text import slugify
from tests.fakes.academic.schedule.emis import FakeEmisSource
from tests.fakes.academic.schedule.identity import (
    FakeIdentity,
    FakeIdentityCommands,
    make_user,
)
from tests.fakes.academic.schedule.reader import FakeScheduleReader
from tests.fakes.academic.schedule.room_cache import FakeRoomPageCache
from tests.fakes.academic.schedule.store import ScheduleStore
from tests.fakes.academic.schedule.uow import uow_factory_for
from tests.fakes.academic.schedule.urls import FakeLessonUrls
from tests.fakes.clock import FixedClock
from tests.fakes.outbox import InMemoryOutbox
from tests.fakes.tasks import FakeTaskKicker

import sqlalchemy as sa
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

TERM_START = dt.date(2026, 9, 1)
TERM_END = dt.date(2026, 12, 25)
TODAY = dt.date(2026, 10, 6)  # the FixedClock day (Tuesday), 14:00 in Tashkent
ROOMS_URL = "http://rooms.test/r"
MAIL_DOMAIN = "mail.test"

EnvKind = Literal["fake", "sql"]


def default_bells() -> list[Bell]:
    """Three periods; Saturday's first period is shorter."""
    return [
        Bell(
            period=1, start=dt.time(8, 30), end=dt.time(9, 15), weekdays=[1, 2, 3, 4, 5]
        ),
        Bell(period=1, start=dt.time(8, 30), end=dt.time(9, 5), weekdays=[6]),
        Bell(
            period=2,
            start=dt.time(9, 25),
            end=dt.time(10, 10),
            weekdays=[1, 2, 3, 4, 5, 6],
        ),
        Bell(
            period=3,
            start=dt.time(10, 20),
            end=dt.time(11, 5),
            weekdays=[1, 2, 3, 4, 5, 6],
        ),
    ]


@dataclass(slots=True)
class Env:
    """Services plus the helpers that seed and read the data behind them."""

    kind: EnvKind
    services: ScheduleServices
    emis_import: EmisImportServices
    emis: FakeEmisSource
    urls: FakeLessonUrls
    uow_factory: UowFactory
    reader: ScheduleReader
    identity: FakeIdentity
    commands: FakeIdentityCommands
    kicker: FakeTaskKicker
    clock: FixedClock
    cache: FakeRoomPageCache
    redis: Redis
    store: ScheduleStore | None = None
    maker: async_sessionmaker[AsyncSession] | None = None
    outbox: InMemoryOutbox | None = None

    # - - - what committed transactions wrote - - -

    @property
    def notifications(self) -> list[NotificationDraft]:
        """Notifications written so far."""
        if self.store is not None:
            return self.store.notifications
        assert self.outbox is not None
        return self.outbox.notifications

    @property
    def audits(self) -> list[AuditDraft]:
        """Audit events written so far."""
        if self.store is not None:
            return self.store.audits
        assert self.outbox is not None
        return self.outbox.audits

    # - - - seeding - - -

    async def term(
        self,
        *,
        starts_on: dt.date = TERM_START,
        ends_on: dt.date = TERM_END,
        academic_year: str = "2026-2027",
        half: int = 1,
        bells: list[Bell] | None = None,
        non_study_days: list[dt.date] | None = None,
        moved_days: list[MovedDay] | None = None,
    ) -> Term:
        """Insert a term (default: Sep 1 - Dec 25 with three bells)."""
        term = Term(
            id=new_id(),
            academic_year=academic_year,
            half=half,
            starts_on=starts_on,
            ends_on=ends_on,
            bells=bells if bells is not None else default_bells(),
            non_study_days=non_study_days or [],
            moved_days=moved_days or [],
        )
        async with self.uow_factory() as uow:
            await uow.terms.add(term)
            await uow.commit()
        return term

    async def subject(
        self,
        ru: str = "Математика",
        *,
        short: str | None = "Мат",
        emis_id: int | None = None,
    ) -> Subject:
        """Insert a subject named in Russian."""
        subject = Subject(
            id=new_id(),
            name={"uz": "", "ru": ru, "en": ""},
            short_name=short,
            emis_subject_id=emis_id,
        )
        async with self.uow_factory() as uow:
            await uow.subjects.add(subject)
            await uow.commit()
        return subject

    async def group(
        self,
        name: str = "2TN2",
        *,
        curator: UserRef | None = None,
        emis_group_id: int | None = None,
        semester: int | None = 3,
    ) -> Group:
        """Insert an active group."""
        group = Group(
            id=new_id(),
            name=name,
            slug=name.lower(),
            emis_group_id=emis_group_id,
            current_semester=semester,
            curator_id=curator.id if curator else None,
        )
        async with self.uow_factory() as uow:
            await uow.groups.add(group)
            await uow.commit()
        return group

    def teacher(
        self, first_name: str = "Gulnora", last_name: str = "Kalandarova"
    ) -> UserRef:
        """Register a teacher in the fake identity module."""
        return self.identity.add(
            make_user(
                first_name=first_name,
                last_name=last_name,
                roles=frozenset({Role.TEACHER}),
                login=f"{last_name}.{first_name}".lower(),
            )
        )

    async def student(
        self,
        group: Group,
        *,
        subgroup: int | None = None,
        first_name: str = "Aliya",
        last_name: str = "Karimova",
        user_status: UserStatus = UserStatus.ACTIVE,
        status: Literal["active", "left"] = "active",
        middle_name: str | None = None,
    ) -> UserRef:
        """Register a student user and insert the academic student row."""
        user = self.identity.add(
            make_user(
                first_name=first_name,
                last_name=last_name,
                middle_name=middle_name,
                status=user_status,
                login=(
                    None
                    if user_status == UserStatus.UNREGISTERED
                    else f"{last_name}.{first_name}".lower()
                ),
            )
        )
        async with self.uow_factory() as uow:
            await uow.students.add(
                Student(
                    user_id=user.id, group_id=group.id, subgroup=subgroup, status=status
                )
            )
            await uow.commit()
        return user

    async def room(
        self, name: str = "102", *, status: Literal["active", "archived"] = "active"
    ) -> Room:
        """Insert a room."""
        room = Room(
            id=new_id(),
            slug=slugify(name) or "room",
            name=name,
            pin=random_digits(6),
            pin_changed_at=self.clock.now(),
            status=status,
        )
        async with self.uow_factory() as uow:
            await uow.rooms.add(room)
            await uow.commit()
        return room

    async def entry(
        self,
        term: Term,
        *,
        weekday: int,
        period: int,
        subject: Subject,
        audience: list[str],
        teacher: UserRef | None = None,
        room: Room | None = None,
        parity: WeekParity = "every",
        valid_from: dt.date | None = None,
        valid_to: dt.date | None = None,
        source: EntrySource = "manual",
    ) -> TimetableEntry:
        """Insert a timetable entry."""
        entry = TimetableEntry(
            id=new_id(),
            term_id=term.id,
            weekday=weekday,
            period=period,
            week_parity=parity,
            subject_id=subject.id,
            teacher_id=teacher.id if teacher else None,
            room_id=room.id if room else None,
            audience=audience,
            valid_from=valid_from or term.starts_on,
            valid_to=valid_to,
            source=source,
        )
        async with self.uow_factory() as uow:
            await uow.entries.add(entry)
            await uow.commit()
        return entry

    async def lesson(
        self,
        term: Term,
        *,
        day: dt.date,
        period: int,
        subject: Subject,
        audience: list[str],
        teacher: UserRef | None = None,
        room: Room | None = None,
        starts_at: dt.datetime | None = None,
        entry: TimetableEntry | None = None,
        overridden: bool = False,
        kind: LessonKind = "other",
        emis_class_id: int | None = None,
        topic: str | None = None,
        emis_topic: str | None = None,
    ) -> Lesson:
        """Insert a lesson (default time: 10:00 Tashkent on the day)."""
        begin = starts_at or (
            dt.datetime.combine(day, dt.time(5, 0), tzinfo=dt.UTC)
            + dt.timedelta(hours=period - 1)
        )
        lesson = Lesson(
            id=new_id(),
            term_id=term.id,
            date=day,
            period=period,
            starts_at=begin,
            ends_at=begin + dt.timedelta(minutes=45),
            subject_id=subject.id,
            teacher_id=teacher.id if teacher else None,
            room_id=room.id if room else None,
            audience=audience,
            is_overridden=overridden,
            timetable_entry_id=entry.id if entry else None,
            origin_date=day if entry else None,
            kind=kind,
            emis_class_id=emis_class_id,
            topic=topic,
            emis_topic=emis_topic,
        )
        async with self.uow_factory() as uow:
            await uow.lessons.add(lesson)
            await uow.commit()
        return lesson

    # - - - reading back and changing what the other modules own - - -

    async def lessons(self) -> list[Lesson]:
        """Return every lesson, ordered by date and period."""
        if self.store is not None:
            found = list(self.store.lessons.values())
        else:
            assert self.maker is not None
            async with self.maker() as session:
                rows = (await session.scalars(sa.select(LessonRow))).all()
                found = [lesson_to_entity(row) for row in rows]
        return sorted(found, key=lambda x: (x.date, x.period, str(x.id)))

    async def give_homework(self, lesson_id: UUID) -> None:
        """Make a lesson "have content", as if the teacher had set homework."""
        if self.store is not None:
            self.store.lessons[lesson_id].has_content = True
            return
        assert self.maker is not None
        async with self.maker() as session:
            await session.execute(
                sa.update(LessonRow)
                .where(LessonRow.id == lesson_id)
                .values(homework_text="Exercise 5")
            )
            await session.commit()

    async def give_mark(
        self, lesson_id: UUID, student: UserRef, subject: Subject
    ) -> None:
        """Attach an EMIS mark to the lesson (SQL only)."""
        assert self.maker is not None
        async with self.maker() as session:
            session.add(
                MarkRow(
                    student_id=student.id,
                    subject_id=subject.id,
                    semester=1,
                    type="lesson",
                    value=5,
                    date=TODAY,
                    ordinal=1,
                    lesson_id=lesson_id,
                )
            )
            await session.commit()


def build_env(
    kind: EnvKind,
    *,
    clock: FixedClock,
    kicker: FakeTaskKicker,
    redis: Redis,
    maker: async_sessionmaker[AsyncSession] | None = None,
    import_topics: bool = False,
) -> Env:
    """Assemble the schedule services on fakes or on PostgreSQL."""
    identity = FakeIdentity()
    commands = FakeIdentityCommands(identity)
    cache = FakeRoomPageCache()
    store: ScheduleStore | None = None
    outbox: InMemoryOutbox | None = None
    reader: Any
    if kind == "fake":
        store = ScheduleStore()
        uow_factory: UowFactory = uow_factory_for(store)  # type: ignore[assignment]
        reader = FakeScheduleReader(store)
    else:
        assert maker is not None
        outbox = InMemoryOutbox()
        sessionmaker = maker

        def sql_factory() -> SqlScheduleUnitOfWork:
            return SqlScheduleUnitOfWork(
                sessionmaker, outbox.write_notifications, outbox.write_audit, None
            )

        uow_factory = sql_factory  # type: ignore[assignment]
        reader = SqlScheduleReader(maker)
    services = assemble_schedule(
        uow_factory=uow_factory,
        reader=reader,
        import_store=RedisImportStore(redis),
        room_cache=cache,
        clock=clock,
        kicker=kicker,
        identity=identity,  # type: ignore[arg-type]
        identity_commands=commands,  # type: ignore[arg-type]
        rooms_url=ROOMS_URL,
        mail_domain=MAIL_DOMAIN,
    )
    emis = FakeEmisSource()
    urls = FakeLessonUrls()
    emis_import = assemble_emis_import(
        uow_factory=uow_factory,
        emis=emis,
        identity_commands=commands,  # type: ignore[arg-type]
        generate=services.generate_lessons,
        urls=urls,
        cache=cache,
        kicker=kicker,
        clock=clock,
        import_topics=import_topics,
    )
    return Env(
        kind=kind,
        services=services,
        emis_import=emis_import,
        emis=emis,
        urls=urls,
        uow_factory=uow_factory,
        reader=reader,
        identity=identity,
        commands=commands,
        kicker=kicker,
        clock=clock,
        cache=cache,
        redis=redis,
        store=store,
        maker=maker,
        outbox=outbox,
    )
