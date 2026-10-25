"""Fixtures of the authoring tests: services on the real database, actors, helpers."""

from collections.abc import Callable
from dataclasses import dataclass
from uuid import UUID

from app.modules.lms.application.authoring.views import CourseDraftView
from app.modules.lms.domain.authoring.enums import Visibility
from app.modules.lms.infrastructure.authoring.uow import SqlAuthoringUnitOfWork
from app.modules.lms.ports.authoring.unit_of_work import AuthoringUnitOfWork
from app.modules.lms.wiring_authoring import AuthoringServices, assemble_authoring
from app.shared.actor import Actor, Role
from app.shared.db.uow_testing import noop_audit_writer, noop_outbox_writer
from tests.fakes.clock import FixedClock
from tests.fakes.lms.files import FakeFilesApi
from tests.fakes.lms.identity import FakeIdentityDirectory

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@pytest.fixture
def identity() -> FakeIdentityDirectory:
    """Users known to the identity directory."""
    return FakeIdentityDirectory()


@pytest.fixture
def files() -> FakeFilesApi:
    """Files known to the files API."""
    return FakeFilesApi()


@pytest.fixture
def services(
    sessionmaker_in_tx: async_sessionmaker[AsyncSession],
    clock: FixedClock,
    identity: FakeIdentityDirectory,
    files: FakeFilesApi,
) -> AuthoringServices:
    """Authoring use cases on SQL repositories, inside the test transaction."""

    def uow_factory() -> AuthoringUnitOfWork:
        return SqlAuthoringUnitOfWork(
            sessionmaker_in_tx, noop_outbox_writer, noop_audit_writer
        )

    return assemble_authoring(uow_factory, clock=clock, identity=identity, files=files)


@dataclass(slots=True)
class Team:
    """Actors of one course; each has the staff row its name says (admin has none)."""

    admin: Actor
    owner: Actor
    teacher: Actor
    tester: Actor
    reviewer: Actor
    outsider: Actor


@pytest.fixture
def admin(make_actor: Callable[..., Actor], identity: FakeIdentityDirectory) -> Actor:
    """An LMS administrator."""
    actor = make_actor(Role.LMS_ADMIN)
    identity.add_user("admin", user_id=actor.user_id, roles=[Role.LMS_ADMIN])
    return actor


@dataclass(slots=True)
class CourseFixture:
    """A course with its team."""

    course: CourseDraftView
    team: Team

    @property
    def id(self) -> UUID:
        """ID of the course."""
        return self.course.id


@pytest.fixture
async def course(
    services: AuthoringServices,
    admin: Actor,
    identity: FakeIdentityDirectory,
    make_actor: Callable[..., Actor],
) -> CourseFixture:
    """A public course; owner, teacher, tester and reviewer are on its staff."""
    created = await services.create_course.execute(
        admin, title="Calculus", slug="calculus", visibility=Visibility.PUBLIC
    )
    people: dict[str, Actor] = {}
    for login, role, permissions in (
        ("owner", "Owner", None),
        ("teacher", "Teacher", None),
        ("tester", "Tester", None),
        ("reviewer", "Reviewer", None),
    ):
        actor = make_actor(Role.TEACHER)
        identity.add_user(login, user_id=actor.user_id, last_name=login.title())
        await services.add_course_staff.execute(
            admin, created.id, login=login, role=role, permissions=permissions
        )
        people[login] = actor
    return CourseFixture(
        course=created,
        team=Team(
            admin=admin,
            owner=people["owner"],
            teacher=people["teacher"],
            tester=people["tester"],
            reviewer=people["reviewer"],
            outsider=make_actor(Role.TEACHER),
        ),
    )
