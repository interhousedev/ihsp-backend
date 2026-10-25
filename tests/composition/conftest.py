"""Fixtures of the composition tests: a world of fakes and clients per caller."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Literal

from app.interfaces.http.dependencies import get_actor
from app.interfaces.http.public.ical import ROUTERS as ICAL_ROUTERS
from app.interfaces.http.v1.composition import ROUTERS as COMPOSITION_ROUTERS
from app.interfaces.http.v1.composition.dependencies import get_composition
from app.interfaces.http.v1.composition.ports import CompositionPorts
from app.interfaces.http.v1.composition.services import Composition
from app.interfaces.http.v1.composition.wiring import build_composition
from app.settings import Settings
from app.shared.actor import Actor, Role
from app.shared.contracts.identity import UserRef, UserStatus
from tests.composition.fakes import (
    FakeAccounts,
    FakeAi,
    FakeAttendance,
    FakeBroadcasts,
    FakeCalendarTokens,
    FakeClasswork,
    FakeFiles,
    FakeFlashcards,
    FakeIdentity,
    FakeMarks,
    FakeOverview,
    FakeSchedule,
    FakeSearchSources,
    FakeStudentViews,
    FakeSync,
    FakeTeacherViews,
    make_student,
    make_user,
)
from tests.conftest import HttpClientFactory
from tests.fakes.clock import FixedClock

import pytest
from httpx import AsyncClient


@dataclass
class World:
    """The fakes behind one composition and the composition itself."""

    settings: Settings
    clock: FixedClock
    composition: Composition
    ports: CompositionPorts
    identity: FakeIdentity = field(default_factory=FakeIdentity)
    schedule: FakeSchedule = field(default_factory=FakeSchedule)
    classwork: FakeClasswork = field(default_factory=FakeClasswork)
    marks: FakeMarks = field(default_factory=FakeMarks)
    ai: FakeAi = field(default_factory=FakeAi)
    flashcards: FakeFlashcards = field(default_factory=FakeFlashcards)
    sources: FakeSearchSources = field(default_factory=FakeSearchSources)
    files: FakeFiles = field(default_factory=FakeFiles)
    sync: FakeSync = field(default_factory=FakeSync)
    tokens: FakeCalendarTokens = field(default_factory=FakeCalendarTokens)
    overview: FakeOverview = field(default_factory=FakeOverview)
    attendance: FakeAttendance = field(default_factory=FakeAttendance)
    students: FakeStudentViews = field(default_factory=FakeStudentViews)
    teachers: FakeTeacherViews = field(default_factory=FakeTeacherViews)
    accounts: FakeAccounts = field(default_factory=FakeAccounts)
    broadcasts: FakeBroadcasts = field(default_factory=FakeBroadcasts)

    def add_student(
        self,
        *,
        subgroup: int | None = 1,
        first_name: str = "Aziza",
        last_name: str = "Karimova",
        status: UserStatus = UserStatus.ACTIVE,
        emis_status: Literal["active", "needs_reauth"] | None = "active",
    ) -> UserRef:
        """Register a student in identity, the schedule and the token store."""
        student = self.identity.add(
            make_user(
                Role.STUDENT,
                first_name=first_name,
                last_name=last_name,
                status=status,
                emis_status=emis_status,
            )
        )
        self.schedule.students[student.id] = make_student(student.id, subgroup=subgroup)
        self.tokens.known_students.add(student.id)
        return student

    def add_user(
        self,
        *roles: Role,
        first_name: str = "Bobur",
        last_name: str = "Tursunov",
        status: UserStatus = UserStatus.ACTIVE,
    ) -> UserRef:
        """Register a user with the roles in identity only."""
        return self.identity.add(
            make_user(*roles, first_name=first_name, last_name=last_name, status=status)
        )


def _build_world(settings: Settings, clock: FixedClock) -> World:
    identity, schedule, classwork = FakeIdentity(), FakeSchedule(), FakeClasswork()
    marks, ai, flashcards = FakeMarks(), FakeAi(), FakeFlashcards()
    files, sync, tokens = FakeFiles(), FakeSync(), FakeCalendarTokens()
    overview, attendance = FakeOverview(), FakeAttendance()
    students, teachers = FakeStudentViews(), FakeTeacherViews()
    accounts, broadcasts = FakeAccounts(), FakeBroadcasts()
    search_sources = FakeSearchSources()
    ports = CompositionPorts(
        files=files,
        search_sources=search_sources,
        sync=sync,
        calendar_tokens=tokens,
        schedule_overview=overview,
        attendance_stats=attendance,
        students=students,
        teachers=teachers,
        accounts=accounts,
        broadcasts=broadcasts,
    )
    composition = build_composition(
        settings=settings,
        clock=clock,
        identity=identity,
        schedule=schedule,
        classwork=classwork,
        marks=marks,
        ai=ai,
        flashcards=flashcards,
        ports=ports,
    )
    return World(
        settings=settings,
        clock=clock,
        composition=composition,
        ports=ports,
        identity=identity,
        schedule=schedule,
        classwork=classwork,
        marks=marks,
        ai=ai,
        flashcards=flashcards,
        sources=search_sources,
        files=files,
        sync=sync,
        tokens=tokens,
        overview=overview,
        attendance=attendance,
        students=students,
        teachers=teachers,
        accounts=accounts,
        broadcasts=broadcasts,
    )


@pytest.fixture
def world(settings: Settings, clock: FixedClock) -> World:
    """A composition over empty fakes (2026-10-06 14:00 in Tashkent)."""
    return _build_world(settings, clock)


ClientFor = Callable[[Actor | None], Awaitable[AsyncClient]]


@pytest.fixture
def client_for(http_client: HttpClientFactory, world: World) -> ClientFor:
    """Factory: a client logged in as the actor (None = anonymous)."""

    async def make(actor: Actor | None = None) -> AsyncClient:
        overrides: dict[Callable[..., object], Callable[..., object]] = {
            get_composition: lambda: world.composition
        }
        if actor is not None:
            overrides[get_actor] = lambda: actor
        return await http_client(
            [*COMPOSITION_ROUTERS, *ICAL_ROUTERS], overrides=overrides
        )

    return make


def actor_of(user: UserRef) -> Actor:
    """Return the actor of a user with the user's roles."""
    return Actor(user_id=user.id, roles=user.roles)
