"""Fixtures of the feedback tests: the module on in-memory fakes."""

from collections.abc import Callable
from dataclasses import dataclass

from app.modules.feedback.ports.people import Person
from app.modules.feedback.wiring import FeedbackOverrides, FeedbackServices, build
from app.settings import Settings
from app.shared.actor import Actor, Role
from app.shared.contracts.files import FilePurpose, FileRef, FileScope
from app.shared.db.uow_testing import noop_audit_writer, noop_outbox_writer
from app.shared.i18n.core import I18nCore
from app.shared.ids import new_id
from app.shared.rate_limit import RateLimiter
from app.shared.wiring import ModuleDeps
from tests.fakes.clock import FixedClock
from tests.fakes.feedback.uow import (
    FakeFeedbackFiles,
    FakeFeedbackStore,
    FakeMailer,
    FakePeople,
    fake_uow_factory,
)
from tests.fakes.tasks import FakeTaskKicker

import pytest
from fakeredis.aioredis import FakeRedis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@dataclass
class FeedbackHarness:
    """The wired module and the fakes behind it."""

    services: FeedbackServices
    store: FakeFeedbackStore
    files: FakeFeedbackFiles
    people: FakePeople
    mailer: FakeMailer
    student: Actor
    admin: Actor

    def file(
        self,
        owner: Actor,
        *,
        name: str = "shot.png",
        content_type: str = "image/png",
        status: str = "ready",
    ) -> FileRef:
        """Store a file of ``owner`` and return it."""
        ref = FileRef(
            id=new_id(),
            owner_id=owner.user_id,
            scope=FileScope.STUDENT,
            purpose=FilePurpose.FEEDBACK,
            name=name,
            content_type=content_type,
            byte_size=42,
            status=status,
            text_bytes=None,
        )
        self.files.files[ref.id] = ref
        return ref

    def person(
        self, actor: Actor, *, login: str | None = None, telegram: bool = False
    ) -> None:
        """Register the actor in the people directory."""
        self.people.persons[actor.user_id] = Person(
            user_id=actor.user_id,
            display_name=f"User {actor.user_id.hex[:4]}",
            roles=tuple(sorted(r.value for r in actor.roles)),
            locale="en",
            group_name="2TN2" if actor.has(Role.STUDENT) else None,
            login=login,
            has_telegram=telegram,
        )


@pytest.fixture
def fb(
    settings: Settings,
    i18n: I18nCore,
    redis: FakeRedis,
    clock: FixedClock,
    kicker: FakeTaskKicker,
    make_actor: Callable[..., Actor],
) -> FeedbackHarness:
    """The module on fakes, with a student and an admin."""
    deps = ModuleDeps(
        settings=settings,
        clock=clock,
        redis=redis,
        sessionmaker=async_sessionmaker(class_=AsyncSession),
        kicker=kicker,
        rate_limiter=RateLimiter(redis),
        i18n=i18n,
        outbox_writer=noop_outbox_writer,
        audit_writer=noop_audit_writer,
        outbox_committed_hook=None,
    )
    store, files, people, mailer = (
        FakeFeedbackStore(),
        FakeFeedbackFiles(),
        FakePeople(),
        FakeMailer(),
    )
    services = build(
        deps,
        files=files,  # type: ignore[arg-type]  # the part of FilesApi feedback uses
        people=people,
        mailer=mailer,
        overrides=FeedbackOverrides(uow_factory=fake_uow_factory(store)),
    )
    harness = FeedbackHarness(
        services,
        store,
        files,
        people,
        mailer,
        make_actor(Role.STUDENT),
        make_actor(Role.ADMIN),
    )
    harness.person(harness.student, login="ali.karimov", telegram=True)
    harness.person(harness.admin)
    people.admins.append(harness.admin.user_id)
    return harness
