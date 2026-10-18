"""Staff filters on custom fields and the distinct-values use case (FILT-CF-*)."""

from app.modules.certificates.application.staff_scope import StaffFilters
from app.modules.certificates.domain.custom_fields import CustomField, FieldKind
from app.modules.certificates.domain.errors import (
    CertificateInvalidError,
    CustomFieldRequiredError,
    NotCuratorError,
)
from app.shared.ids import new_id
from tests.certificates.conftest import CertificatesHarness

import pytest

LABEL = {"uz": "x", "ru": "x", "en": "x"}


def fields() -> list[CustomField]:
    """Track (choices, other allowed), note (text) and score (number)."""
    return [
        CustomField(
            "track",
            FieldKind.MULTI,
            LABEL,
            options=("math", "art"),
            allow_other=True,
        ),
        CustomField("note", FieldKind.TEXT, LABEL),
        CustomField("score", FieldKind.NUMBER, LABEL, required=True),
    ]


async def seed(h: CertificatesHarness) -> None:
    """Ann, Bob and Cid each have one entry of the SAT type."""
    kind = await h.add_type("sat", custom_fields=fields())
    await h.add_entry(
        h.ann, kind, custom={"track": ["math"], "note": "a", "score": 700}
    )
    await h.add_entry(
        h.bob, kind, custom={"track": ["Chess club"], "note": "b", "score": 300}
    )
    await h.add_entry(
        h.cid, kind, custom={"track": ["art", "math"], "note": "a", "score": 900}
    )


async def names(h: CertificatesHarness, flt: StaffFilters) -> list[str]:
    """Names of the students whose entries match, for the admin."""
    page = await h.services.list_staff_entries.execute(h.admin, flt, limit=50, offset=0)
    return sorted(view.student.name for view in page.items)


async def test_choice_filter_is_a_multi_select(h: CertificatesHarness) -> None:
    """FILT-CF-01: any selected value matches; several fields combine with AND."""
    await seed(h)
    kind_id = next(iter(h.store.types))

    by_track = StaffFilters(type_id=kind_id, custom={"track": ("art", "Chess club")})
    combined = StaffFilters(
        type_id=kind_id, custom={"track": ("math",), "note": ("a",)}
    )

    assert await names(h, by_track) == ["Bob Beta", "Cid Gamma"]
    assert await names(h, combined) == ["Ann Alpha", "Cid Gamma"]


async def test_number_filter_is_a_range(h: CertificatesHarness) -> None:
    """FILT-CF-02: min and max bound the number, either end may be open."""
    await seed(h)
    kind_id = next(iter(h.store.types))

    between = StaffFilters(type_id=kind_id, ranges={"score": (500.0, 800.0)})
    at_least = StaffFilters(type_id=kind_id, ranges={"score": (800.0, None)})

    assert await names(h, between) == ["Ann Alpha"]
    assert await names(h, at_least) == ["Cid Gamma"]


async def test_custom_filters_need_one_type(h: CertificatesHarness) -> None:
    """FILT-CF-03: without a type the custom filters are not applied."""
    await seed(h)

    assert await names(h, StaffFilters(custom={"track": ("art",)})) == [
        "Ann Alpha",
        "Bob Beta",
        "Cid Gamma",
    ]


async def test_values_list_choices_and_other_values(h: CertificatesHarness) -> None:
    """FILT-CF-04: defined options plus the free-text values, below them."""
    await seed(h)
    kind_id = next(iter(h.store.types))

    values = await h.services.list_custom_field_values.execute(
        h.admin, StaffFilters(type_id=kind_id), "track"
    )

    assert values.options == ["math", "art"]
    assert values.other_values == ["Chess club"]


async def test_text_values_are_distinct_and_numbers_have_bounds(
    h: CertificatesHarness,
) -> None:
    """FILT-CF-05: text lists distinct values; number lists min and max."""
    await seed(h)
    kind_id = next(iter(h.store.types))

    note = await h.services.list_custom_field_values.execute(
        h.admin, StaffFilters(type_id=kind_id), "note"
    )
    score = await h.services.list_custom_field_values.execute(
        h.admin, StaffFilters(type_id=kind_id), "score"
    )

    assert note.other_values == ["a", "b"]
    assert (score.min, score.max) == (300.0, 900.0)


async def test_values_need_a_type_and_a_known_field(h: CertificatesHarness) -> None:
    """FILT-CF-06: no type or an unknown field key is refused."""
    await seed(h)
    kind_id = next(iter(h.store.types))

    with pytest.raises(CertificateInvalidError):
        await h.services.list_custom_field_values.execute(h.admin, StaffFilters(), "x")
    with pytest.raises(CertificateInvalidError):
        await h.services.list_custom_field_values.execute(
            h.admin, StaffFilters(type_id=kind_id), "nope"
        )


async def test_a_required_custom_field_is_enforced_on_create(
    h: CertificatesHarness,
) -> None:
    """FILT-CF-07: the required number missing on create is refused."""
    kind = await h.add_type("sat", custom_fields=fields())

    with pytest.raises(CustomFieldRequiredError):
        await h.add_entry(h.ann, kind, custom={"note": "x"})


async def test_a_scope_of_other_students_hides_values(h: CertificatesHarness) -> None:
    """FILT-CF-08: a curator cannot list values for a group outside their curation."""
    await seed(h)
    kind_id = next(iter(h.store.types))
    curator_scope = StaffFilters(type_id=kind_id, group_id=new_id())

    with pytest.raises(NotCuratorError):
        await h.services.list_custom_field_values.execute(
            h.curator, curator_scope, "note"
        )
