"""LIB-12: the on/off switch is off by default and Administration can set it."""

from app.modules.library.domain.errors import ExternalDisabledError
from app.modules.library.ports.external_settings import ExternalFlags
from app.modules.library.wiring_external import ExternalServices
from app.shared.actor import Actor
from app.shared.base_error import ForbiddenError
from app.shared.redis_util import wait
from tests.fakes.library.external_catalog import FakeExternalCatalog, make_record

import pytest
from fakeredis.aioredis import FakeRedis


async def test_the_environment_decides_until_administration_sets_a_value(
    external: ExternalServices, external_off: ExternalServices, admin: Actor
) -> None:
    """LIB-12: `LIBRARY__UNILIBRARY_ENABLED` is the default."""
    assert await external.get_settings.execute(admin) == ExternalFlags(
        enabled=True, anonymous_cards=False
    )
    assert await external_off.get_settings.execute(admin) == ExternalFlags(
        enabled=False, anonymous_cards=False
    )


async def test_the_override_replaces_the_environment(
    external_off: ExternalServices, admin: Actor, redis: FakeRedis
) -> None:
    """LIB-12: `PUT .../settings` lives in Redis `library:ext:settings`."""
    saved = await external_off.put_settings.execute(
        admin, enabled=True, anonymous_cards=True
    )

    assert saved == ExternalFlags(enabled=True, anonymous_cards=True)
    assert await wait(redis.hgetall("library:ext:settings")) == {
        "enabled": "1",
        "anonymous_cards": "1",
    }
    assert await external_off.get_settings.execute(admin) == saved


async def test_switching_on_opens_the_user_endpoints_without_a_restart(
    external_off: ExternalServices,
    catalog: FakeExternalCatalog,
    admin: Actor,
    student: Actor,
) -> None:
    """LIB-12: the flag is read on every request."""
    catalog.add(make_record("1"))
    with pytest.raises(ExternalDisabledError):
        await external_off.get_card.execute(student, "1", category=1)

    await external_off.put_settings.execute(admin, enabled=True, anonymous_cards=False)

    card = await external_off.get_card.execute(student, "1", category=1)
    assert card.title == "Elektronika va sxemalar 1"


async def test_switching_off_closes_them_again(
    external: ExternalServices, admin: Actor, student: Actor
) -> None:
    """LIB-12: the override beats an enabled environment."""
    await external.put_settings.execute(admin, enabled=False, anonymous_cards=False)

    with pytest.raises(ExternalDisabledError):
        await external.get_card.execute(student, "1", category=1)


async def test_gate_exposes_the_effective_flags_to_other_areas(
    external: ExternalServices, admin: Actor
) -> None:
    """LIB-12: the catalogue asks the gate for `anonymous_cards`."""
    await external.put_settings.execute(admin, enabled=True, anonymous_cards=True)

    flags = await external.gate.flags()

    assert flags.anonymous_cards is True


async def test_only_administration_changes_the_settings(
    external: ExternalServices, student: Actor, librarian: Actor
) -> None:
    """LIB-12: students and librarians are refused."""
    for actor in (student, librarian):
        with pytest.raises(ForbiddenError):
            await external.put_settings.execute(
                actor, enabled=True, anonymous_cards=True
            )
        with pytest.raises(ForbiddenError):
            await external.get_settings.execute(actor)
