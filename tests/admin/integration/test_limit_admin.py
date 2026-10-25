"""Runtime limits on the test database: overrides, resets, extensions, audit."""

from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from app.modules.admin.application.limit_admin import LimitAdmin, LimitUserNotFoundError
from app.modules.admin.domain.limits import ExtensionTerms, LimitInvalidError
from app.modules.admin.infrastructure.limit_snapshot import load_limit_snapshot
from app.modules.admin.wiring import build as build_admin
from app.modules.notify.infrastructure.outbox_writer import write_notifications
from app.settings import Settings
from app.shared.actor import Actor, Role
from app.shared.base_error import ForbiddenError
from app.shared.clock import local_today
from app.shared.i18n.core import I18nCore
from app.shared.ids import new_id
from app.shared.limits import EffectiveLimits
from app.shared.rate_limit import RateLimiter
from app.shared.wiring import ModuleDeps
from tests.factories.notify import make_user
from tests.fakes.clock import FixedClock
from tests.fakes.notify.identity import FakeIdentityDirectory
from tests.fakes.notify.schedule import FakeScheduleQueries
from tests.fakes.tasks import FakeTaskKicker

import pytest
from fakeredis.aioredis import FakeRedis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@dataclass
class World:
    admin: LimitAdmin
    provider: EffectiveLimits
    admin_actor: Actor
    student_actor: Actor
    student_id: Any
    audits: list[Any]


@pytest.fixture
def world(
    settings: Settings,
    clock: FixedClock,
    redis: FakeRedis,
    kicker: FakeTaskKicker,
    i18n: I18nCore,
    sessionmaker_in_tx: async_sessionmaker[AsyncSession],
) -> World:
    identity = FakeIdentityDirectory()
    admin_user = identity.add_user(make_user(Role.ADMIN, first_name="Gulnora"), 900)
    student = identity.add_user(
        make_user(
            Role.STUDENT, first_name="Aziza", last_name="Karimova", user_id=new_id()
        ),
        901,
    )
    audits: list[Any] = []

    async def capture(_: AsyncSession, drafts: list[Any]) -> None:
        audits.extend(drafts)

    provider = EffectiveLimits(
        settings.limits,
        lambda: load_limit_snapshot(sessionmaker_in_tx),
        today=lambda: local_today(clock),
    )
    deps = ModuleDeps(
        settings=settings,
        clock=clock,
        redis=redis,
        sessionmaker=sessionmaker_in_tx,
        kicker=kicker,
        rate_limiter=RateLimiter(redis),
        i18n=i18n,
        outbox_writer=write_notifications,
        audit_writer=capture,
        outbox_committed_hook=None,
        limits=provider,
    )
    services = build_admin(deps, identity=identity, schedule=FakeScheduleQueries())
    return World(
        admin=services.limit_admin,
        provider=provider,
        admin_actor=Actor(user_id=admin_user.id, roles=frozenset({Role.ADMIN})),
        student_actor=Actor(user_id=student.id, roles=frozenset({Role.STUDENT})),
        student_id=student.id,
        audits=audits,
    )


def value_of(rows: list[Any], key: str) -> Any:
    return next(row for row in rows if row.spec.key == key)


async def test_a_change_applies_at_once_and_is_audited(world: World) -> None:
    rows = await world.admin.update(world.admin_actor, {"nb_chat_per_minute": 25})

    row = value_of(rows, "nb_chat_per_minute")
    assert (row.value, row.default, row.overridden) == (25, 10, True)
    assert (await world.provider.current()).nb_chat_per_minute == 25
    (draft,) = world.audits
    assert draft.type == "admin.limits_changed"
    assert draft.actor_id == world.admin_actor.user_id
    assert draft.metadata == {"changes": {"nb_chat_per_minute": {"old": 10, "new": 25}}}


async def test_a_null_resets_a_limit_to_its_environment_value(world: World) -> None:
    await world.admin.update(world.admin_actor, {"nb_chat_per_minute": 25})

    rows = await world.admin.update(world.admin_actor, {"nb_chat_per_minute": None})

    row = value_of(rows, "nb_chat_per_minute")
    assert (row.value, row.overridden) == (10, False)
    assert (await world.provider.current()).nb_chat_per_minute == 10


async def test_an_invalid_change_is_refused_and_changes_nothing(world: World) -> None:
    with pytest.raises(LimitInvalidError):
        await world.admin.update(world.admin_actor, {"nb_chat_per_minute": -1})
    with pytest.raises(LimitInvalidError):
        await world.admin.update(world.admin_actor, {"lms_ai_session_tokens": 5})

    assert world.audits == []
    rows = await world.admin.catalogue(world.admin_actor)
    assert not any(row.overridden for row in rows)


async def test_only_administration_changes_or_reads_the_limits(world: World) -> None:
    with pytest.raises(ForbiddenError):
        await world.admin.update(world.student_actor, {"nb_chat_per_minute": 25})
    with pytest.raises(ForbiddenError):
        await world.admin.catalogue(world.student_actor)


async def test_an_extension_applies_lists_and_is_removed_with_its_audit(
    world: World,
) -> None:
    row = await world.admin.save_extension(
        world.admin_actor,
        world.student_id,
        ExtensionTerms(multiplier=3, note="  thesis  "),
    )

    assert row.record.terms.note == "thesis"
    assert row.active is True
    base = Settings().limits.ai_daily_tokens_student
    assert (
        await world.provider.for_user(world.student_id, unlimited=False)
    ).ai_daily_tokens_student == 3 * base
    listed = await world.admin.extensions(world.admin_actor, user_id=world.student_id)
    assert listed[0].user is not None and listed[0].user.first_name == "Aziza"
    assert [draft.type for draft in world.audits] == ["admin.limit_extension_saved"]

    assert (
        await world.admin.delete_extension(world.admin_actor, world.student_id) is True
    )
    assert (
        await world.provider.for_user(world.student_id, unlimited=False)
    ).ai_daily_tokens_student == base
    assert (
        await world.admin.delete_extension(world.admin_actor, world.student_id) is False
    )


async def test_an_extension_is_for_an_existing_student_only(world: World) -> None:
    with pytest.raises(LimitUserNotFoundError):
        await world.admin.save_extension(
            world.admin_actor, uuid4(), ExtensionTerms(multiplier=2)
        )


async def test_an_override_and_an_extension_combine_on_the_stored_values(
    world: World,
) -> None:
    await world.admin.update(world.admin_actor, {"ai_daily_tokens_student": 1_000_000})
    await world.admin.save_extension(
        world.admin_actor, world.student_id, ExtensionTerms(multiplier=2)
    )

    view = await world.provider.for_user(world.student_id, unlimited=False)

    assert view.ai_daily_tokens_student == 2_000_000
