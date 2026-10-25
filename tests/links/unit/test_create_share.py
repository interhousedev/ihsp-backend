"""SHR-1, SHR-3, SHR-8: creating shares of chats and flash card sets."""

from datetime import timedelta

from app.modules.links.domain.errors import InvalidExpiryError, ShareNotAllowedError
from app.modules.links.domain.link import LinkKind, ShareMode
from tests.fakes.clock import FixedClock
from tests.fakes.links.world import LinksWorld

import pytest


async def test_chat_share_uses_the_c_prefix_and_the_share_origin(
    world: LinksWorld,
) -> None:
    """SHR-1: `s.ihsu.uz/ai/c-{uuid}` for chats."""
    ann = world.person("Ann")
    chat = world.ai.add_chat(ann.user_id, [("user", "hi"), ("assistant", "hello")])

    view = await world.services.create_share.execute(
        ann, kind=LinkKind.CHAT, target_id=chat
    )

    assert view.link.slug.startswith("c-")
    assert view.url == f"http://localhost:3006/ai/{view.link.slug}"
    assert view.link.target_id == chat


async def test_snapshot_is_the_default_and_fixes_the_last_message(
    world: LinksWorld,
) -> None:
    """SHR-3: snapshot shares keep the sequence number at the share moment."""
    ann = world.person("Ann")
    chat = world.ai.add_chat(ann.user_id, [("user", "a"), ("assistant", "b")])

    view = await world.services.create_share.execute(
        ann, kind=LinkKind.CHAT, target_id=chat
    )

    assert view.link.share_mode is ShareMode.SNAPSHOT
    assert view.link.snapshot_seq == 2


async def test_live_share_has_no_snapshot_point(world: LinksWorld) -> None:
    """SHR-3: live shares show later messages."""
    ann = world.person("Ann")
    chat = world.ai.add_chat(ann.user_id, [("user", "a")])

    view = await world.services.create_share.execute(
        ann, kind=LinkKind.CHAT, target_id=chat, share_mode=ShareMode.LIVE
    )

    assert view.link.share_mode is ShareMode.LIVE
    assert view.link.snapshot_seq is None


async def test_flashcard_share_uses_the_f_prefix(world: LinksWorld) -> None:
    """SHR-1: `s.ihsu.uz/ai/f-{uuid}` for sets; no share mode."""
    ann = world.person("Ann")
    cards = world.flashcards.add_set(ann.user_id, [("hola", "hello")])

    view = await world.services.create_share.execute(
        ann, kind=LinkKind.FLASHCARD_SET, target_id=cards, share_mode=ShareMode.LIVE
    )

    assert view.link.slug.startswith("f-")
    assert view.link.share_mode is None


async def test_share_of_an_administration_chat_is_forbidden(world: LinksWorld) -> None:
    """SHR-1, AI-12: administration chats never leave the platform."""
    ann = world.person("Ann")
    chat = world.ai.add_chat(ann.user_id, [("user", "secret")], admin=True)

    with pytest.raises(ShareNotAllowedError) as error:
        await world.services.create_share.execute(
            ann, kind=LinkKind.CHAT, target_id=chat
        )

    assert error.value.status == 403


async def test_nobody_shares_a_chat_or_set_of_someone_else(world: LinksWorld) -> None:
    """SHR-1: only the owner shares."""
    ann, bob = world.person("Ann"), world.person("Bob")
    chat = world.ai.add_chat(ann.user_id, [("user", "a")])
    cards = world.flashcards.add_set(ann.user_id, [("a", "b")])

    with pytest.raises(ShareNotAllowedError):
        await world.services.create_share.execute(
            bob, kind=LinkKind.CHAT, target_id=chat
        )
    with pytest.raises(ShareNotAllowedError):
        await world.services.create_share.execute(
            bob, kind=LinkKind.FLASHCARD_SET, target_id=cards
        )


async def test_expiry_must_be_in_the_future(
    world: LinksWorld, clock: FixedClock
) -> None:
    """SHR-8: a share can expire, but not in the past."""
    ann = world.person("Ann")
    chat = world.ai.add_chat(ann.user_id, [("user", "a")])

    with pytest.raises(InvalidExpiryError):
        await world.services.create_share.execute(
            ann, kind=LinkKind.CHAT, target_id=chat, expires_at=clock.now()
        )
    view = await world.services.create_share.execute(
        ann,
        kind=LinkKind.CHAT,
        target_id=chat,
        expires_at=clock.now() + timedelta(days=7),
    )

    assert view.link.expires_at == clock.now() + timedelta(days=7)


async def test_revoking_a_share_marks_it_revoked_but_keeps_it_listed(
    world: LinksWorld,
) -> None:
    """SHR-6: revoked shares stay in the list with their revocation time."""
    ann = world.person("Ann")
    chat = world.ai.add_chat(ann.user_id, [("user", "a")])
    view = await world.services.create_share.execute(
        ann, kind=LinkKind.CHAT, target_id=chat
    )

    revoked = await world.services.revoke_link.execute(ann, view.link.id)
    page = await world.services.list_my_links.execute(
        ann, kind=LinkKind.CHAT, target_id=chat
    )

    assert revoked.link.revoked_at is not None
    assert [item.link.id for item in page.items] == [view.link.id]


async def test_share_resolves_through_the_public_api_until_revoked(
    world: LinksWorld,
) -> None:
    """LinksApi.resolve_share: kind and target of an active share."""
    ann = world.person("Ann")
    cards = world.flashcards.add_set(ann.user_id, [("a", "b")])
    view = await world.services.create_share.execute(
        ann, kind=LinkKind.FLASHCARD_SET, target_id=cards
    )

    found = await world.services.public.resolve_share(view.link.slug)
    await world.services.revoke_link.execute(ann, view.link.id)
    gone = await world.services.public.resolve_share(view.link.slug)

    assert found == ("flashcard_set", cards)
    assert gone is None
    assert await world.services.public.resolve_share("missing") is None
