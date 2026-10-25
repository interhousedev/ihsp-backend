"""SL-2, SL-3: short ID alphabet, reserved IDs, lengths and collisions."""

import random
from datetime import UTC, datetime
from uuid import UUID

from app.modules.links.application.slug_allocator import SlugAllocator
from app.modules.links.domain.errors import SlugsExhaustedError, SlugTakenError
from app.modules.links.domain.link import Link, LinkKind
from app.modules.links.domain.short_id import (
    FILE_LENGTH,
    RESERVED,
    URL_LENGTH,
    generate,
    is_lookup_slug,
    is_valid,
    new_slug,
)
from app.shared.ids import SHORT_ID_PREFERRED, new_id
from tests.fakes.links.uow import FakeUowFactory

import pytest
from hypothesis import given
from hypothesis import strategies as st

EXCLUDED = set("0OoIlL.")


@given(
    st.integers(min_value=1, max_value=64), st.integers(min_value=0, max_value=10**6)
)
def test_generated_ids_never_contain_excluded_characters(
    length: int, seed: int
) -> None:
    """SL-2: no 0, O, o, I, L, l or dot, whatever the random source returns."""
    slug = generate(length, random.Random(seed))

    assert len(slug) == length
    assert not EXCLUDED & set(slug)


def test_generator_prefers_digits_and_symbols() -> None:
    """SL-2: roughly 70% of characters come from the preferred set."""
    slug = generate(4000, random.Random(1))

    share = sum(ch in SHORT_ID_PREFERRED for ch in slug) / len(slug)
    assert 0.65 < share < 0.85


@pytest.mark.parametrize("slug", sorted(RESERVED))
def test_reserved_words_are_not_valid_ids(slug: str) -> None:
    """SL-2: reserved IDs are never generated or accepted."""
    assert not is_valid(slug)


@pytest.mark.parametrize("slug", ["a", "_aB", "9d-K4m_x", "7_k", "~"])
def test_one_character_and_long_ids_are_valid(slug: str) -> None:
    """SL-2: no fixed length."""
    assert is_valid(slug)


@pytest.mark.parametrize("slug", ["", "a0b", "hello.world", "c-123", "f-abc", "l1l"])
def test_forbidden_characters_and_share_prefixes_are_invalid(slug: str) -> None:
    """SL-2: 0, dot, l and the share prefixes are not short IDs."""
    assert not is_valid(slug)


def test_lookup_slug_check_skips_obviously_invalid_input() -> None:
    """SL-10: strange input is a 404 without touching the database."""
    assert is_lookup_slug("9d-K4m_x")
    assert not is_lookup_slug("x" * 65)
    assert not is_lookup_slug("a b")


def test_urls_get_three_characters_files_eight_and_shares_a_uuid() -> None:
    """SL-2, SL-3, SHR-1: lengths and share slugs."""
    rng = random.Random(3)

    url = new_slug(LinkKind.URL, rng)
    file = new_slug(LinkKind.FILE, rng)
    chat = new_slug(LinkKind.CHAT, rng)
    cards = new_slug(LinkKind.FLASHCARD_SET, rng)

    assert len(url) == URL_LENGTH
    assert len(file) == FILE_LENGTH
    assert chat.startswith("c-") and UUID(chat[2:]).version == 4
    assert cards.startswith("f-") and UUID(cards[2:]).version == 4


def test_length_grows_by_one_after_five_collisions_in_a_row() -> None:
    """SL-2: collisions grow the ID."""
    rng = random.Random(3)

    assert len(new_slug(LinkKind.URL, rng, failures=4)) == 3
    assert len(new_slug(LinkKind.URL, rng, failures=5)) == 4
    assert len(new_slug(LinkKind.URL, rng, failures=10)) == 5


def test_only_admins_may_request_short_ids() -> None:
    """SL-2: 1-2 character IDs are for Administration."""
    rng = random.Random(3)

    assert len(new_slug(LinkKind.URL, rng, requested_length=1, is_admin=True)) == 1
    assert len(new_slug(LinkKind.URL, rng, requested_length=1, is_admin=False)) == 3


def _link(slug: str) -> Link:
    return Link(
        id=new_id(),
        slug=slug,
        kind=LinkKind.URL,
        owner_id=new_id(),
        created_at=datetime(2026, 10, 6, tzinfo=UTC),
        target_url="https://example.org/",
    )


async def test_allocator_retries_on_collision() -> None:
    """SL-2: a taken slug is retried with a new random one."""
    taken = new_slug(LinkKind.URL, random.Random(5))
    factory = FakeUowFactory()
    async with factory() as uow:
        await uow.links.add(_link(taken))
        link = await SlugAllocator(random.Random(5)).add(uow, _link, kind=LinkKind.URL)

    assert link.slug != taken
    assert len(link.slug) == URL_LENGTH


async def test_allocator_grows_the_slug_after_five_collisions() -> None:
    """SL-2: five collisions in a row make the next candidate one character longer."""
    rng = random.Random(5)
    taken = [new_slug(LinkKind.URL, rng, failures=i) for i in range(5)]
    factory = FakeUowFactory()
    async with factory() as uow:
        for slug in dict.fromkeys(taken):
            await uow.links.add(_link(slug))
        link = await SlugAllocator(random.Random(5)).add(uow, _link, kind=LinkKind.URL)

    assert len(link.slug) == URL_LENGTH + 1


async def test_allocator_gives_up_when_nothing_is_free() -> None:
    """SL-2: an exhausted ID space raises a clean error."""

    class AlwaysTaken:
        async def add(self, link: Link) -> None:
            raise SlugTakenError(link.slug)

    class Uow:
        links = AlwaysTaken()

    allocator = SlugAllocator(random.Random(1))

    with pytest.raises(SlugsExhaustedError):
        await allocator.add(Uow(), _link, kind=LinkKind.URL)  # type: ignore[arg-type]
