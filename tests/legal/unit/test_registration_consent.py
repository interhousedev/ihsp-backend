"""Registration requires the current version of every published document."""

from app.modules.identity.application.register_errors import ConsentRequiredError
from app.shared.contracts.legal import LegalItem
from tests.identity.emis.test_register_complete import code_for, prepared
from tests.identity.emis.world import NEW_PASSWORD, World
from tests.legal.conftest import LegalHarness

import pytest


async def finish(world: World, token: str, items: list[LegalItem]) -> None:
    await world.register_complete.execute(
        registration_token=token,
        password=NEW_PASSWORD,
        email_code=code_for(world, token),
        confirm_import_match=True,
        login_challenge=None,
        ip="10.0.0.1",
        user_agent="pytest",
        accepted_legal=items,
    )


async def test_no_consent_needed_when_nothing_is_published(
    world: World, legal: LegalHarness
) -> None:
    """An empty legal catalogue does not block registration."""
    world.register_complete._consent = legal.services.hooks.consent
    token = await prepared(world)
    await finish(world, token, [])
    assert world.ledger.consents == []


async def test_registration_requires_every_published_kind(
    world: World, legal: LegalHarness
) -> None:
    """Missing, partial or stale acceptance answers legal/consent-required."""
    await legal.publish("privacy")
    await legal.publish("terms")
    await legal.publish("terms")
    world.register_complete._consent = legal.services.hooks.consent
    token = await prepared(world)
    for items in (
        [],
        [LegalItem("privacy", 1)],
        [LegalItem("privacy", 1), LegalItem("terms", 1)],
    ):
        with pytest.raises(ConsentRequiredError) as info:
            await finish(world, token, items)
        assert info.value.code == "legal/consent-required"
    assert info.value.params == {"kinds": "terms"}
    assert not world.repo.accounts


async def test_registration_records_the_acceptances(
    world: World, legal: LegalHarness
) -> None:
    """The acceptances ride the account's transaction."""
    await legal.publish("privacy")
    await legal.publish("terms")
    world.register_complete._consent = legal.services.hooks.consent
    token = await prepared(world)
    await finish(world, token, [LegalItem("privacy", 1), LegalItem("terms", 1)])
    [draft] = world.ledger.consents
    assert set(draft.items) == {LegalItem("privacy", 1), LegalItem("terms", 1)}
    assert draft.ip == "10.0.0.1"
    assert draft.user_id in world.repo.accounts
