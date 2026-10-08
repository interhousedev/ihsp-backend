"""SL-1, SL-3, SL-7, SL-10: creating, listing and deleting short links."""

from datetime import timedelta

from app.modules.links.domain.errors import (
    BlockedUrlError,
    FileNotReadyError,
    InvalidLinkTargetError,
    LinkNotFoundError,
)
from app.modules.links.domain.link import LinkKind
from app.shared.actor import Role
from app.shared.base_error import ForbiddenError, RateLimitedError
from tests.fakes.clock import FixedClock
from tests.fakes.links.world import LinksWorld

import pytest


async def test_url_link_gets_a_three_character_slug_and_a_title(
    world: LinksWorld,
) -> None:
    """SL-1, SL-2, UF-WEB-26: a pasted URL is shortened and titled."""
    ann = world.person("Ann")

    view = await world.services.create_link.execute(
        ann, kind=LinkKind.URL, target_url="https://example.org/lecture"
    )

    assert len(view.link.slug) == 3
    assert view.url == f"http://localhost:8000/s/{view.link.slug}"
    assert view.link.title == "Title of https://example.org/lecture"
    assert view.link.owner_id == ann.user_id
    assert (
        world.uow.store.links[view.link.id].target_url == "https://example.org/lecture"
    )


async def test_file_link_gets_an_eight_character_slug(world: LinksWorld) -> None:
    """SL-3: files get long random IDs."""
    ann = world.person("Ann")
    file = world.files.add(ann.user_id, name="Lecture 5.pdf")

    view = await world.services.create_link.execute(
        ann, kind=LinkKind.FILE, file_id=file.id
    )

    assert len(view.link.slug) == 8
    assert view.file == file


@pytest.mark.parametrize("status", ["pending", "processing", "rejected", "deleted"])
async def test_file_must_be_ready(world: LinksWorld, status: str) -> None:
    """UF-WEB-07: only verified files can be published."""
    ann = world.person("Ann")
    file = world.files.add(ann.user_id, status=status)

    with pytest.raises(FileNotReadyError):
        await world.services.create_link.execute(
            ann, kind=LinkKind.FILE, file_id=file.id
        )


async def test_file_of_another_user_is_refused(world: LinksWorld) -> None:
    """SL-1: a user cannot publish someone else's file."""
    ann, bob = world.person("Ann"), world.person("Bob")
    file = world.files.add(bob.user_id)

    with pytest.raises(FileNotReadyError):
        await world.services.create_link.execute(
            ann, kind=LinkKind.FILE, file_id=file.id
        )


async def test_blocked_domain_is_refused_with_422(world: LinksWorld) -> None:
    """SL-8, UF-WEB-07 alternative 2d."""
    with pytest.raises(BlockedUrlError) as error:
        await world.services.create_link.execute(
            world.person("Ann"),
            kind=LinkKind.URL,
            target_url="https://blocked.example/x",
        )

    assert error.value.status == 422


@pytest.mark.parametrize(
    ("kind", "url", "has_file"),
    [
        (LinkKind.URL, None, False),
        (LinkKind.URL, "https://example.org/", True),
        (LinkKind.FILE, None, False),
        (LinkKind.FILE, "https://example.org/", True),
        (LinkKind.CHAT, "https://example.org/", False),
    ],
)
async def test_target_must_match_the_kind(
    world: LinksWorld, kind: LinkKind, url: str | None, has_file: bool
) -> None:
    """Link checks: url ⇔ target_url, file ⇔ file_id."""
    ann = world.person("Ann")
    file_id = world.files.add(ann.user_id).id if has_file else None

    with pytest.raises(InvalidLinkTargetError):
        await world.services.create_link.execute(
            ann, kind=kind, target_url=url, file_id=file_id
        )


async def test_the_sixty_first_link_in_an_hour_is_rate_limited(
    world: LinksWorld,
) -> None:
    """SL-10: link creation is limited per user."""
    ann = world.person("Ann")
    for _ in range(60):
        await world.services.create_link.execute(
            ann, kind=LinkKind.URL, target_url="https://example.org/"
        )

    with pytest.raises(RateLimitedError):
        await world.services.create_link.execute(
            ann, kind=LinkKind.URL, target_url="https://example.org/"
        )


async def test_only_admins_choose_the_slug_length(world: LinksWorld) -> None:
    """SL-2: 1-2 character IDs are reserved for Administration."""
    admin = world.person("Root", Role.ADMIN)
    student = world.person("Ann")

    short = await world.services.create_link.execute(
        admin, kind=LinkKind.URL, target_url="https://example.org/", requested_length=2
    )
    with pytest.raises(ForbiddenError):
        await world.services.create_link.execute(
            student,
            kind=LinkKind.URL,
            target_url="https://example.org/",
            requested_length=2,
        )

    assert len(short.link.slug) == 2


async def test_listing_pages_newest_first_and_filters_by_kind(
    world: LinksWorld,
) -> None:
    """SL-7, UF-WEB-26: own links, newest first, filterable."""
    ann, bob = world.person("Ann"), world.person("Bob")
    created = []
    for index in range(3):
        view = await world.services.create_link.execute(
            ann, kind=LinkKind.URL, target_url=f"https://example.org/{index}"
        )
        created.append(view.link.id)
    file = world.files.add(ann.user_id)
    file_link = await world.services.create_link.execute(
        ann, kind=LinkKind.FILE, file_id=file.id
    )
    await world.services.create_link.execute(
        bob, kind=LinkKind.URL, target_url="https://example.org/bob"
    )

    first = await world.services.list_my_links.execute(ann, limit=3)
    second = await world.services.list_my_links.execute(
        ann, limit=3, cursor=first.next_cursor
    )
    files_only = await world.services.list_my_links.execute(ann, kind=LinkKind.FILE)

    assert [v.link.id for v in first.items] == [
        file_link.link.id,
        created[2],
        created[1],
    ]
    assert first.next_cursor is not None
    assert [v.link.id for v in second.items] == [created[0]]
    assert second.next_cursor is None
    assert [v.link.id for v in files_only.items] == [file_link.link.id]
    assert files_only.items[0].file == file


async def test_deleted_link_leaves_the_list_and_only_the_owner_can_delete(
    world: LinksWorld,
) -> None:
    """SL-7: deletion is by the owner; the link is not listed afterwards."""
    ann, bob = world.person("Ann"), world.person("Bob")
    view = await world.services.create_link.execute(
        ann, kind=LinkKind.URL, target_url="https://example.org/"
    )

    with pytest.raises(LinkNotFoundError):
        await world.services.delete_link.execute(bob, view.link.id)
    await world.services.delete_link.execute(ann, view.link.id)

    stored = world.uow.store.links[view.link.id]
    page = await world.services.list_my_links.execute(ann)
    assert stored.revoked_at is not None
    assert page.items == []


async def test_repeated_delete_keeps_the_first_revocation_time(
    world: LinksWorld, clock: FixedClock
) -> None:
    """SL-7: ID reuse is blocked for 90 days from the first deletion."""
    ann = world.person("Ann")
    view = await world.services.create_link.execute(
        ann, kind=LinkKind.URL, target_url="https://example.org/"
    )
    await world.services.delete_link.execute(ann, view.link.id)
    first = world.uow.store.links[view.link.id].revoked_at
    clock.advance(hours=1)

    await world.services.delete_link.execute(ann, view.link.id)

    assert world.uow.store.links[view.link.id].revoked_at == first
    assert first is not None
    assert clock.now() - first == timedelta(hours=1)
