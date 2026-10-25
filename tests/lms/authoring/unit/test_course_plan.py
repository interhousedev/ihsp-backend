"""LMS-6: a course plan is parsed, limited and matched with the draft outline."""

from typing import Any
from uuid import UUID

from app.modules.lms.domain.authoring.course_plan import (
    MAX_BRIEF_LENGTH,
    MAX_SECTIONS,
    MAX_STEPS_PER_SECTION,
    PlanAction,
    match_plan,
    parse_plan,
    title_key,
)
from app.modules.lms.domain.authoring.errors import (
    PlanInvalidError,
    TitleInvalidError,
)
from app.shared.ids import new_id

import pytest


def _section(title: str, *steps: str, brief: str | None = None) -> dict[str, Any]:
    return {
        "title": title,
        "steps": [{"title": s, **({"brief": brief} if brief else {})} for s in steps],
    }


def test_titles_are_compared_without_case_and_extra_spaces() -> None:
    """The matching key ignores case, leading, trailing and repeated spaces."""
    assert title_key("  Limits   and\tContinuity ") == title_key(
        "limits and continuity"
    )
    assert title_key("STRASSE") == title_key("straße")
    assert title_key("Limits") != title_key("Limit")


def test_a_plan_is_parsed_with_clean_titles_and_briefs() -> None:
    """Titles are trimmed, a missing brief is empty, extra keys are ignored."""
    planned = parse_plan(
        [
            {
                "title": "  Limits ",
                "goals": ["ignored"],
                "steps": [{"title": " Idea ", "brief": "  why  "}, {"title": "Rules"}],
            }
        ]
    )

    assert [s.title for s in planned] == ["Limits"]
    assert [(st.title, st.brief) for st in planned[0].steps] == [
        ("Idea", "why"),
        ("Rules", ""),
    ]


def test_a_section_may_have_no_steps() -> None:
    """The steps are optional: the plan can only add a section."""
    planned = parse_plan([{"title": "Empty"}])

    assert planned[0].steps == ()


@pytest.mark.parametrize(
    "sections",
    [
        [],
        [_section(f"S{i}") for i in range(MAX_SECTIONS + 1)],
        [_section("S", *[f"T{i}" for i in range(MAX_STEPS_PER_SECTION + 1)])],
        [_section("S", "T", brief="x" * (MAX_BRIEF_LENGTH + 1))],
        [{"steps": []}],
        [{"title": 5}],
        [{"title": "S", "steps": "not a list"}],
        [{"title": "S", "steps": ["not an object"]}],
        [{"title": "S", "steps": [{"title": "T", "brief": ["x"]}]}],
    ],
)
def test_limits_and_wrong_shapes_are_a_plan_error(sections: list[Any]) -> None:
    """At most 30 sections, 30 steps each, briefs up to 20,000 characters."""
    with pytest.raises(PlanInvalidError) as caught:
        parse_plan(sections)

    assert caught.value.params["max_sections"] == 30
    assert caught.value.params["max_steps"] == 30
    assert caught.value.params["max_brief"] == 20_000


def test_the_limits_themselves_are_allowed() -> None:
    """30 sections of 30 steps with 20,000 character briefs pass."""
    sections = [
        _section(f"S{i}", *[f"T{j}" for j in range(30)]) for i in range(MAX_SECTIONS)
    ]
    sections[0]["steps"][0]["brief"] = "x" * MAX_BRIEF_LENGTH

    planned = parse_plan(sections)

    assert len(planned) == 30 and len(planned[0].steps) == 30


@pytest.mark.parametrize("title", ["", "   ", "x" * 201])
def test_empty_and_overlong_titles_are_title_errors(title: str) -> None:
    """Titles go through the same 1..200 rule as every other title."""
    with pytest.raises(TitleInvalidError):
        parse_plan([_section(title)])
    with pytest.raises(TitleInvalidError):
        parse_plan([_section("S", title)])


def _outline() -> tuple[dict[str, Any], dict[UUID, str], UUID, UUID]:
    a, b = new_id(), new_id()
    outline = {
        "sections": [
            {"id": "s1", "title": "Limits", "steps": [str(a)]},
            {"id": "s2", "title": "Derivatives", "steps": [str(b)]},
        ]
    }
    return outline, {a: "Idea of a limit", b: "Rules"}, a, b


def test_existing_sections_and_steps_match_whatever_the_case_and_spacing() -> None:
    """A section or step found by its title is `exists` and carries its ID."""
    outline, titles, a, _ = _outline()

    plan = match_plan(
        outline,
        titles,
        parse_plan([_section("  LIMITS ", "idea   of a LIMIT", "Continuity")]),
    )

    assert [(s.action, s.section_id) for s in plan] == [(PlanAction.EXISTS, "s1")]
    assert [(s.action, s.step_id) for s in plan[0].steps] == [
        (PlanAction.EXISTS, a),
        (PlanAction.NEW, None),
    ]


def test_a_new_section_has_only_new_steps_and_no_ids() -> None:
    """Nothing in a section the draft lacks can exist yet."""
    outline, titles, _, _ = _outline()

    plan = match_plan(outline, titles, parse_plan([_section("Integrals", "Rules")]))

    assert plan[0].action is PlanAction.NEW and plan[0].section_id is None
    assert [(s.action, s.step_id) for s in plan[0].steps] == [(PlanAction.NEW, None)]


def test_a_step_with_the_title_of_a_step_in_another_section_is_new() -> None:
    """Steps are matched inside their section only."""
    outline, titles, _, _ = _outline()

    plan = match_plan(outline, titles, parse_plan([_section("Limits", "Rules")]))

    assert [s.action for s in plan[0].steps] == [PlanAction.NEW]


def test_the_first_of_several_equal_titles_in_the_draft_wins() -> None:
    """Duplicate titles in the draft are not an error; the first one counts."""
    first, second = new_id(), new_id()
    outline = {
        "sections": [
            {"id": "s1", "title": "A", "steps": [str(first), str(second)]},
            {"id": "s2", "title": "a", "steps": []},
        ]
    }

    plan = match_plan(
        outline, {first: "Same", second: "same"}, parse_plan([_section("A", "SAME")])
    )

    assert plan[0].section_id == "s1" and plan[0].steps[0].step_id == first


def test_a_step_missing_from_the_database_is_ignored() -> None:
    """An outline entry without a step row cannot be matched."""
    ghost = new_id()
    outline = {"sections": [{"id": "s1", "title": "A", "steps": [str(ghost)]}]}

    plan = match_plan(outline, {}, parse_plan([_section("A", "T")]))

    assert plan[0].action is PlanAction.EXISTS
    assert plan[0].steps[0].action is PlanAction.NEW
