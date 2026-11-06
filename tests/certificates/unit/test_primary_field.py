"""Priority star: one starred field per type; stats group or average by it (PF-*)."""

import importlib.util
from dataclasses import replace
from pathlib import Path
from types import ModuleType

from app.modules.certificates.application.staff_scope import StaffFilters
from app.modules.certificates.domain.custom_fields import (
    CustomField,
    FieldKind,
    check_fields,
    field_from_dict,
)
from app.modules.certificates.domain.errors import CertificateInvalidError
from tests.certificates.conftest import (
    CertificatesHarness,
    label,
    number_field,
    text_field,
)

import pytest

MIGRATION = (
    Path(__file__).parents[3] / "migrations/versions/certificates/certificates_0004.py"
)


def _migration() -> ModuleType:
    """Load the data migration as a module (its file name starts with a digit)."""
    spec = importlib.util.spec_from_file_location("certificates_0004", MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def starred(item: CustomField) -> CustomField:
    """The same field, with its star."""
    return replace(item, primary=True)


def test_a_starred_flag_survives_the_json_form() -> None:
    """PF-01: the star is stored on the field; a field without it is not starred."""
    starred_field = starred(number_field("score"))

    assert field_from_dict(starred_field.to_dict()).primary is True
    assert field_from_dict(
        {"key": "x", "kind": "text", "label": label("x")}
    ).primary is (False)


@pytest.mark.parametrize(
    "item",
    [
        number_field("score"),
        text_field("note"),
        CustomField("track", FieldKind.SINGLE, label("track"), options=("a", "b")),
    ],
)
def test_number_text_and_single_fields_can_be_starred(item: CustomField) -> None:
    """PF-02: a number, a text or a single choice field may carry the star."""
    check_fields([starred(item)])


def test_a_type_has_at_most_one_star() -> None:
    """PF-03: two starred fields in one type are refused."""
    with pytest.raises(CertificateInvalidError):
        check_fields([starred(number_field("score")), starred(text_field("note"))])


def test_a_multi_choice_field_cannot_be_starred() -> None:
    """PF-04: several choices have no single value to group by."""
    multi = CustomField("langs", FieldKind.MULTI, label("langs"), options=("a", "b"))

    with pytest.raises(CertificateInvalidError):
        check_fields([starred(multi)])


async def test_stats_group_and_average_by_the_starred_number(
    h: CertificatesHarness,
) -> None:
    """PF-05: a starred number gives a distribution per group and the averages."""
    kind = await h.add_type("sat", custom_fields=[starred(number_field("score"))])
    await h.add_entry(h.ann, kind, custom={"score": 1200})
    await h.add_entry(h.ann, kind, custom={"score": 1400})
    await h.add_entry(h.bob, kind, custom={"score": 1200})
    await h.add_entry(h.cid, kind, custom={"score": 900})

    [stats] = await h.services.get_staff_stats.execute(h.admin, StaffFilters())

    assert stats.primary_key == "score"
    assert stats.primary_kind is FieldKind.NUMBER
    assert stats.levels == ["900", "1200", "1400"]
    assert [(g.group_name, g.counts) for g in stats.groups] == [
        ("2TN1", {"1200": 2, "1400": 1}),
        ("2TN2", {"900": 1}),
    ]
    assert stats.groups[0].average == pytest.approx(3800 / 3)
    assert stats.groups[1].average == pytest.approx(900.0)
    assert stats.average == pytest.approx(4700 / 4)


async def test_stats_count_a_starred_text_field_with_a_dash_for_none(
    h: CertificatesHarness,
) -> None:
    """PF-06: a starred text field counts its values; no average; none is the dash."""
    kind = await h.add_type("sat", custom_fields=[starred(text_field("subject"))])
    await h.add_entry(h.ann, kind, custom={"subject": "English"})
    await h.add_entry(h.ann, kind, custom={"subject": "German"})
    await h.add_entry(h.bob, kind)
    await h.add_entry(h.cid, kind, custom={"subject": "English"})

    [stats] = await h.services.get_staff_stats.execute(h.admin, StaffFilters())

    assert stats.primary_key == "subject"
    assert stats.primary_kind is FieldKind.TEXT
    assert stats.levels == ["English", "German", "—"]
    assert [(g.group_name, g.counts) for g in stats.groups] == [
        ("2TN1", {"English": 1, "German": 1, "—": 1}),
        ("2TN2", {"English": 1}),
    ]
    assert stats.groups[0].average is None
    assert stats.average is None


def test_seed_stars_the_score_of_sat_and_the_level_of_ielts() -> None:
    """PF-07: the migration stars SAT's score and IELTS's level by stable codes."""
    migration = _migration()
    sat = [
        {"key": "score", "kind": "number"},
        {"key": "note", "kind": "text"},
    ]
    ielts = [{"key": "level", "kind": "single"}, {"key": "subject", "kind": "text"}]

    starred_sat = migration.starred_fields("sat", sat)
    starred_ielts = migration.starred_fields("ielts", ielts)

    assert [(f["key"], f["primary"]) for f in starred_sat] == [
        ("score", True),
        ("note", False),
    ]
    assert [(f["key"], f["primary"]) for f in starred_ielts] == [
        ("level", True),
        ("subject", False),
    ]


def test_seed_leaves_other_types_and_starred_types_alone() -> None:
    """PF-08: other codes, types without the key and types already starred are kept."""
    migration = _migration()
    fields = [{"key": "score", "kind": "number"}]
    already = [
        {"key": "score", "kind": "number", "primary": False},
        {"key": "note", "kind": "text", "primary": True},
    ]

    assert migration.starred_fields("cefr", fields) == fields
    assert migration.starred_fields("sat", [{"key": "note", "kind": "text"}]) == [
        {"key": "note", "kind": "text"}
    ]
    assert migration.starred_fields("sat", already) == already


def test_a_stored_star_on_a_multi_field_is_ignored_on_load() -> None:
    """PF-03: data from before the rule (or the star migration) cannot star a multi."""
    item = CustomField("tags", FieldKind.MULTI, label("tags"), options=("a", "b"))
    loaded = field_from_dict({**item.to_dict(), "primary": True})

    assert loaded.primary is False
    check_fields([loaded])
