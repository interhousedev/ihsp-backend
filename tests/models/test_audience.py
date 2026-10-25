"""Audience keys (ACA-6): whole group, one subgroup, merged lessons."""

from uuid import UUID

from app.modules.academic.domain import audience

from hypothesis import given
from hypothesis import strategies as st

GROUP = UUID("0192f3c4-0000-7000-8000-000000000001")
OTHER = UUID("0192f3c4-0000-7000-8000-000000000002")


def test_whole_group_key_is_the_bare_group_id() -> None:
    assert audience.key(GROUP, None) == str(GROUP)


def test_subgroup_key_has_the_subgroup_after_a_colon() -> None:
    assert audience.key(GROUP, 2) == f"{GROUP}:2"


def test_parse_splits_a_whole_group_key() -> None:
    assert audience.parse(str(GROUP)) == (GROUP, None)


def test_parse_splits_a_subgroup_key() -> None:
    assert audience.parse(f"{GROUP}:1") == (GROUP, 1)


@given(st.uuids(), st.one_of(st.none(), st.sampled_from([1, 2])))
def test_parse_is_the_inverse_of_key(group_id: UUID, subgroup: int | None) -> None:
    assert audience.parse(audience.key(group_id, subgroup)) == (group_id, subgroup)


def test_student_with_a_subgroup_matches_the_group_and_that_subgroup() -> None:
    assert audience.student_keys(GROUP, 2) == [str(GROUP), f"{GROUP}:2"]


def test_student_without_a_subgroup_matches_both_subgroups() -> None:
    assert audience.student_keys(GROUP, None) == [
        str(GROUP),
        f"{GROUP}:1",
        f"{GROUP}:2",
    ]


def test_group_ids_collects_the_groups_of_a_merged_lesson() -> None:
    keys = [f"{GROUP}:2", f"{OTHER}:2", str(GROUP)]

    assert audience.group_ids(keys) == {GROUP, OTHER}
