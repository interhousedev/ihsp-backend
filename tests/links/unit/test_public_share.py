"""SHR-2..SHR-7, UF-PUB-01/02: reading shares without logging in."""

from datetime import timedelta
from uuid import UUID

from app.modules.links.domain.errors import (
    LinkDisabledError,
    LinkGoneError,
    LinkNotFoundError,
    ShareNotAllowedError,
)
from app.modules.links.domain.link import Link, LinkKind, ShareMode
from app.shared.actor import Actor, Role
from app.shared.base_error import RateLimitedError
from app.shared.ids import new_id
from tests.fakes.clock import FixedClock
from tests.fakes.links.world import LinksWorld

import pytest

IP = "203.0.113.7"


async def _share_chat(
    world: LinksWorld, mode: ShareMode | None = None
) -> tuple[Actor, UUID, Link]:
    ann = world.person("Ann")
    chat = world.ai.add_chat(
        ann.user_id, [("user", "What is a derivative?"), ("assistant", "A rate.")]
    )
    view = await world.services.create_share.execute(
        ann, kind=LinkKind.CHAT, target_id=chat, share_mode=mode
    )
    return ann, chat, view.link


async def test_chat_share_shows_title_author_and_messages(world: LinksWorld) -> None:
    """SHR-2, SHR-4, UF-PUB-01: title, author's first name, messages."""
    _, _, link = await _share_chat(world)

    view = await world.services.get_public_share.execute(link.slug, ip=IP)

    assert view.kind == "chat"
    assert view.title == "Derivatives"
    assert view.author_first_name == "Ann"
    assert view.created_at == link.created_at
    assert view.chat is not None
    assert [(m.role, m.text) for m in view.chat] == [
        ("user", "What is a derivative?"),
        ("assistant", "A rate."),
    ]
    assert view.flashcards is None


async def test_snapshot_share_hides_later_messages(world: LinksWorld) -> None:
    """SHR-3: a snapshot ends at the share moment."""
    _, chat, link = await _share_chat(world, ShareMode.SNAPSHOT)
    world.ai.append(chat, "user", "A later question")

    view = await world.services.get_public_share.execute(link.slug, ip=IP)

    assert view.chat is not None
    assert len(view.chat) == 2


async def test_live_share_shows_later_messages(world: LinksWorld) -> None:
    """SHR-3: live shares include new messages."""
    _, chat, link = await _share_chat(world, ShareMode.LIVE)
    world.ai.append(chat, "user", "A later question")

    view = await world.services.get_public_share.execute(link.slug, ip=IP)

    assert view.chat is not None
    assert len(view.chat) == 3


async def test_flashcard_share_lists_the_cards(world: LinksWorld) -> None:
    """SHR-5, UF-PUB-02: the set and its cards, live."""
    ann = world.person("Ann")
    cards = world.flashcards.add_set(ann.user_id, [("hola", "hello"), ("adiós", "bye")])
    link = (
        await world.services.create_share.execute(
            ann, kind=LinkKind.FLASHCARD_SET, target_id=cards
        )
    ).link

    view = await world.services.get_public_share.execute(link.slug, ip=IP)

    assert view.kind == "flashcard_set"
    assert view.flashcards is not None
    assert [(c.front, c.back) for c in view.flashcards] == [
        ("hola", "hello"),
        ("adiós", "bye"),
    ]
    assert view.chat is None


async def test_views_are_counted(world: LinksWorld) -> None:
    """SHR: hits are incremented for shares too."""
    _, _, link = await _share_chat(world)

    await world.services.get_public_share.execute(link.slug, ip=IP)
    await world.services.get_public_share.execute(link.slug, ip=IP)

    assert await world.redis.get(f"links:hits:{link.id}") == "2"


async def test_revoked_share_is_gone(world: LinksWorld) -> None:
    """SHR-6, UF-PUB-01 1a: 410 for revoked shares."""
    ann, _, link = await _share_chat(world)
    await world.services.revoke_link.execute(ann, link.id)

    with pytest.raises(LinkGoneError) as error:
        await world.services.get_public_share.execute(link.slug, ip=IP)

    assert error.value.status == 410


async def test_expired_share_is_gone(world: LinksWorld, clock: FixedClock) -> None:
    """SHR-8: expired shares answer 410."""
    ann = world.person("Ann")
    chat = world.ai.add_chat(ann.user_id, [("user", "a")])
    link = (
        await world.services.create_share.execute(
            ann,
            kind=LinkKind.CHAT,
            target_id=chat,
            expires_at=clock.now() + timedelta(hours=1),
        )
    ).link
    clock.advance(hours=2)

    with pytest.raises(LinkGoneError):
        await world.services.get_public_share.execute(link.slug, ip=IP)


async def test_disabled_share_is_gone_with_its_own_code(world: LinksWorld) -> None:
    """ADM-13: disabled shares answer 410."""
    admin = world.person("Root", Role.ADMIN)
    _, _, link = await _share_chat(world)
    await world.services.disable_link.execute(admin, link.id, "personal data")

    with pytest.raises(LinkDisabledError) as error:
        await world.services.get_public_share.execute(link.slug, ip=IP)

    assert error.value.status == 410


async def test_deleted_chat_makes_the_share_gone(world: LinksWorld) -> None:
    """SHR-7: when the chat is deleted its shares are gone."""
    _, chat, link = await _share_chat(world)
    del world.ai.chats[chat]

    with pytest.raises(LinkGoneError):
        await world.services.get_public_share.execute(link.slug, ip=IP)


@pytest.mark.parametrize("slug", ["x-123", "c-unknown", "f-unknown", "7_k", "", "c-"])
async def test_wrong_prefix_or_unknown_uuid_is_a_404(
    world: LinksWorld, slug: str
) -> None:
    """UF-PUB-01 1b: wrong prefix or unknown UUID."""
    with pytest.raises(LinkNotFoundError) as error:
        await world.services.get_public_share.execute(slug, ip=IP)

    assert error.value.status == 404


async def test_chat_prefix_cannot_open_a_flashcard_share(world: LinksWorld) -> None:
    """The slug prefix and the link kind must agree."""
    ann = world.person("Ann")
    cards = world.flashcards.add_set(ann.user_id, [("a", "b")])
    link = (
        await world.services.create_share.execute(
            ann, kind=LinkKind.FLASHCARD_SET, target_id=cards
        )
    ).link
    stored = world.uow.store.links[link.id]
    stored.slug = "c-" + stored.slug[2:]

    with pytest.raises(LinkNotFoundError):
        await world.services.get_public_share.execute(stored.slug, ip=IP)


async def test_404s_on_the_share_api_use_the_same_ip_budget(world: LinksWorld) -> None:
    """SL-10: scanning share slugs is rate limited."""
    for _ in range(60):
        with pytest.raises(LinkNotFoundError):
            await world.services.get_public_share.execute(f"c-{new_id()}", ip=IP)

    with pytest.raises(RateLimitedError):
        await world.services.get_public_share.execute(f"c-{new_id()}", ip=IP)


async def test_artifact_share_is_read_without_login_and_revoked_is_404(
    world: LinksWorld,
) -> None:
    """A Studio output share opens read-only for anyone; revoking makes it a 404."""
    ann = world.person("Ann")
    content = {"cards": [{"id": "1", "front": "hola", "back": "hello"}]}
    artifact = world.notebooks.add_artifact(ann.user_id, "flashcards", content)
    view = await world.services.create_share.execute(
        ann, kind=LinkKind.ARTIFACT, target_id=artifact
    )
    assert view.link.slug.startswith("a-")
    assert view.link.title == "Cells"

    shared = await world.services.get_public_share.execute(view.link.slug, ip=IP)

    assert shared.kind == "artifact"
    assert shared.author_first_name == "Ann"
    assert shared.artifact is not None
    assert shared.artifact.kind == "flashcards"
    assert shared.artifact.content == content

    await world.services.revoke_link.execute(ann, view.link.id)
    with pytest.raises(LinkNotFoundError) as error:
        await world.services.get_public_share.execute(view.link.slug, ip=IP)
    assert error.value.status == 404


async def test_only_the_owner_shares_an_output(world: LinksWorld) -> None:
    """Someone else's or a missing output cannot be shared."""
    ann, bob = world.person("Ann"), world.person("Bob")
    artifact = world.notebooks.add_artifact(ann.user_id, "quiz", {"questions": []})

    with pytest.raises(ShareNotAllowedError):
        await world.services.create_share.execute(
            bob, kind=LinkKind.ARTIFACT, target_id=artifact
        )
    with pytest.raises(ShareNotAllowedError):
        await world.services.create_share.execute(
            ann, kind=LinkKind.ARTIFACT, target_id=new_id()
        )
