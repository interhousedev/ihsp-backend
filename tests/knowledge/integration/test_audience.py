"""Audience filter: guests see guest entries, students student entries, staff all."""

from tests.knowledge.conftest import KnowledgeHarness

import pytest


async def _seed(h: KnowledgeHarness) -> None:
    await h.add("open day", "The open day is on Saturday", accessible_to_guest=True)
    await h.add("canteen menu", "The canteen menu changes every week")
    await h.add(
        "staff room",
        "The staff room is on the third floor",
        accessible_to_student=False,
    )


@pytest.mark.parametrize(
    ("audience", "expected"),
    [
        ("guest", {"open day"}),
        ("student", {"open day", "canteen menu"}),
        ("staff", {"open day", "canteen menu", "staff room"}),
    ],
)
async def test_each_audience_sees_only_its_entries(
    h: KnowledgeHarness, audience: str, expected: set[str]
) -> None:
    """Visibility flags decide what each audience can find."""
    await _seed(h)

    found = await h.services.public.search("the", limit=10, audience=audience)

    assert {hit.key for hit in found} == expected


async def test_defaults_are_guest_false_and_student_true(h: KnowledgeHarness) -> None:
    """A new entry is hidden from guests and visible to students by default."""
    entry = await h.services.create_entry.execute(
        h.admin.user_id, key="bus", value="The bus leaves at eight"
    )

    assert entry.accessible_to_guest is False
    assert entry.accessible_to_student is True


async def test_update_changes_the_flags(h: KnowledgeHarness) -> None:
    """Update sets the flags; the other fields stay as they were."""
    entry = await h.services.create_entry.execute(
        h.admin.user_id, key="gate", value="The gate opens at seven"
    )

    changed = await h.services.update_entry.execute(
        entry.id, {"accessible_to_guest": True, "accessible_to_student": False}
    )

    assert changed.accessible_to_guest is True
    assert changed.accessible_to_student is False
    assert changed.key == "gate"
    found = await h.services.public.search("gate", limit=5, audience="guest")
    assert [hit.key for hit in found] == ["gate"]


async def test_admin_list_is_not_filtered_by_audience(h: KnowledgeHarness) -> None:
    """The administrator list shows every entry, flags aside."""
    await _seed(h)

    page = await h.services.list_entries.execute(q="the")

    assert {i.entry.key for i in page.items} == {
        "open day",
        "canteen menu",
        "staff room",
    }
