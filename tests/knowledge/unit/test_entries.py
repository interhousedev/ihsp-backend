"""KB-02: create, change and delete entries; embedding follows the text."""

from uuid import uuid4

from app.modules.knowledge.domain.entry import embed_text
from app.modules.knowledge.domain.errors import (
    KnowledgeEntryNotFoundError,
    KnowledgeInvalidError,
    KnowledgeKeyTakenError,
)
from app.shared.contracts.ai import AiProviderError
from tests.knowledge.conftest import KnowledgeHarness

import pytest


async def test_create_stores_a_normalized_entry_and_embeds_it(
    fake_h: KnowledgeHarness,
) -> None:
    """KB-02: key lower case, tags normalized, key + title + value embedded."""
    entry = await fake_h.services.create_entry.execute(
        fake_h.admin.user_id,
        key=" Wifi Password ",
        title="Guest network",
        value="The password is hunter2",
        tags=["IT", "it"],
    )

    assert entry.key == "wifi password"
    assert entry.tags == ["it"]
    assert entry.author_id == fake_h.admin.user_id
    assert fake_h.gateway.texts == [embed_text(entry)]
    assert "Guest network" in fake_h.gateway.texts[0]


async def test_duplicate_key_ignores_case(fake_h: KnowledgeHarness) -> None:
    """KB-02: a second entry with the same key in another case is a conflict."""
    await fake_h.add("Exam Rules", "Bring a pen")

    with pytest.raises(KnowledgeKeyTakenError):
        await fake_h.add("exam rules", "other")


async def test_empty_value_is_invalid(fake_h: KnowledgeHarness) -> None:
    """KB-02: validation errors come from the domain."""
    with pytest.raises(KnowledgeInvalidError):
        await fake_h.add("k", "   ")


async def test_update_re_embeds_when_the_text_changes(
    fake_h: KnowledgeHarness,
) -> None:
    """KB-02: a new value gets a new vector; the old vector stays shared."""
    entry = await fake_h.services.create_entry.execute(
        fake_h.admin.user_id, key="gym", value="Open at 9"
    )
    old_hash = entry.content_hash

    changed = await fake_h.services.update_entry.execute(
        entry.id, {"value": "Open at 10", "tags": ["sport"]}
    )

    assert changed.content_hash != old_hash
    assert changed.tags == ["sport"]
    assert fake_h.gateway.texts[-1].endswith("Open at 10")
    assert len(fake_h.gateway.texts) == 2


async def test_update_to_a_taken_key_conflicts(fake_h: KnowledgeHarness) -> None:
    """KB-02: renaming onto another entry's key fails; keeping your own works."""
    await fake_h.add("a", "1")
    entry = await fake_h.services.create_entry.execute(
        fake_h.admin.user_id, key="b", value="2"
    )

    with pytest.raises(KnowledgeKeyTakenError):
        await fake_h.services.update_entry.execute(entry.id, {"key": "A"})
    same = await fake_h.services.update_entry.execute(entry.id, {"key": "B"})
    assert same.key == "b"


async def test_a_failing_embedding_does_not_fail_the_save(
    fake_h: KnowledgeHarness,
) -> None:
    """KB-02: the entry is saved; words still find it."""
    fake_h.gateway.error = AiProviderError()

    await fake_h.add("lockers", "Lockers are on the 2nd floor")

    found = await fake_h.services.public.search("lockers", audience="student")
    assert [hit.key for hit in found] == ["lockers"]


async def test_delete_and_missing_entry(fake_h: KnowledgeHarness) -> None:
    """KB-02: delete removes the entry; unknown ids are 404."""
    entry = await fake_h.services.create_entry.execute(
        fake_h.admin.user_id, key="x", value="y"
    )

    await fake_h.services.delete_entry.execute(entry.id)

    with pytest.raises(KnowledgeEntryNotFoundError):
        await fake_h.services.get_entry.execute(entry.id)
    with pytest.raises(KnowledgeEntryNotFoundError):
        await fake_h.services.delete_entry.execute(uuid4())
