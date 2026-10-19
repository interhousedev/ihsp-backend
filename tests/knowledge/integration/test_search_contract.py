"""KB-03: hybrid search and listing; one suite on the fakes and on PostgreSQL."""

from tests.fakes.clock import FixedClock
from tests.knowledge.conftest import KnowledgeHarness


async def _seed(h: KnowledgeHarness) -> None:
    await h.add("wifi password", "The guest wifi password is hunter2", tags=["it"])
    await h.add("exam rules", "Bring a pen and a student card to every exam")
    await h.add("canteen hours", "The canteen is open from 9 to 15", tags=["food"])


async def test_search_finds_by_key_and_by_a_word_of_the_value(
    h: KnowledgeHarness,
) -> None:
    """KB-03: the key, and a partial word of the value, both hit."""
    await _seed(h)

    by_key = await h.services.public.search("wifi password")
    by_word = await h.services.public.search("canteen")

    assert by_key[0].key == "wifi password"
    assert by_word[0].key == "canteen hours"
    assert by_key[0].tags == ("it",)


async def test_search_finds_a_partial_word(h: KnowledgeHarness) -> None:
    """KB-03: a word start matches (prefix of a word)."""
    await _seed(h)

    found = await h.services.public.search("passw")

    assert [hit.key for hit in found][:1] == ["wifi password"]


async def test_unrelated_query_finds_nothing(h: KnowledgeHarness) -> None:
    """KB-03: weak signals are dropped by the thresholds."""
    await _seed(h)

    assert await h.services.public.search("zzqx") == []
    assert await h.services.public.search("   ") == []


async def test_limit_and_score_order(h: KnowledgeHarness) -> None:
    """KB-03: at most `limit` hits, best score first."""
    await _seed(h)

    found = await h.services.public.search("the", limit=2)

    assert len(found) <= 2
    assert [hit.score for hit in found] == sorted(
        (hit.score for hit in found), reverse=True
    )


async def test_hit_by_both_signals_outranks_a_single_signal(
    h: KnowledgeHarness,
) -> None:
    """KB-03: rank fusion rewards agreement of words and meaning."""
    await _seed(h)

    [top, *_] = await h.services.public.search("guest wifi password")

    assert top.key == "wifi password"
    assert top.score > 1 / 61  # more than a first place in one ranking


async def test_tags_filter_search_and_list(h: KnowledgeHarness) -> None:
    """KB-03: `tags` keeps entries that carry all of them."""
    await _seed(h)

    page = await h.services.list_entries.execute(tags=["food"])
    searched = await h.services.list_entries.execute(q="the", tags=["it"])

    assert [i.entry.key for i in page.items] == ["canteen hours"]
    assert page.total == 1
    assert {i.entry.key for i in searched.items} <= {"wifi password"}


async def test_list_without_q_is_newest_change_first(
    h: KnowledgeHarness, clock: FixedClock
) -> None:
    """KB-03: ordered by updated_at descending, with total, limit and offset."""
    await h.add("one", "1")
    clock.advance(hours=1)
    await h.add("two", "2")
    clock.advance(hours=1)
    await h.add("three", "3")

    page = await h.services.list_entries.execute(limit=2, offset=0)
    rest = await h.services.list_entries.execute(limit=2, offset=2)

    assert [i.entry.key for i in page.items] == ["three", "two"]
    assert page.total == 3
    assert [i.entry.key for i in rest.items] == ["one"]


async def test_deleted_entry_is_not_found(h: KnowledgeHarness) -> None:
    """KB-03: delete removes the entry from search."""
    await _seed(h)
    [hit] = await h.services.public.search("exam rules", limit=1)
    page = await h.services.list_entries.execute(q="exam rules")

    await h.services.delete_entry.execute(page.items[0].entry.id)

    assert hit.key == "exam rules"
    left = await h.services.public.search("exam rules")
    assert "exam rules" not in [item.key for item in left]
