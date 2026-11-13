"""Honours: red diploma and medal rules over semester and control marks."""

from collections.abc import Sequence
from dataclasses import replace
from uuid import UUID, uuid4

from app.modules.academic.domain.marks.honours import (
    AwardResult,
    SubjectSemesterMarks,
    evaluate,
    serial_matches,
)
from app.shared.contracts.honours import FlagRule, HonoursRules, MaxFoursRule

MATH = uuid4()
PHYS = uuid4()


def row(
    subject: UUID,
    mark: int,
    controls: Sequence[tuple[str, int]] = (),
    semester: int = 1,
) -> SubjectSemesterMarks:
    return SubjectSemesterMarks(subject, "S", semester, mark, tuple(controls))


def by_kind(
    rules: HonoursRules, rows: list[SubjectSemesterMarks], serial: str | None = "TM-A"
) -> dict[str, AwardResult]:
    return {a.kind: a for a in evaluate(rules, rows, serial)}


def test_all_fives_win_every_award() -> None:
    """Every default rule passes for an all-five student with a medal serial."""
    rows = [row(MATH, 5, [("midterm", 5), ("final", 5)]), row(PHYS, 5)]
    awards = by_kind(HonoursRules(), rows)
    assert all(a.eligible for a in awards.values())
    assert set(awards) == {"red_diploma", "gold_medal", "silver_medal"}


def test_red_diploma_blocks_a_mark_below_four_and_too_many_fours() -> None:
    """A 3 blocks; two 4s exceed the maximum of one and are all listed."""
    low = by_kind(HonoursRules(), [row(MATH, 3), row(PHYS, 5)])["red_diploma"]
    assert not low.eligible
    assert [b.value for b in low.rules[0].blocking] == [3]
    fours = by_kind(HonoursRules(), [row(MATH, 4), row(PHYS, 4)])["red_diploma"]
    assert not fours.eligible
    assert [b.value for b in fours.rules[0].blocking] == [4, 4]
    one = by_kind(HonoursRules(), [row(MATH, 4), row(PHYS, 5)])["red_diploma"]
    assert one.eligible


def test_gold_blocks_non_five_controls_and_semester_marks() -> None:
    """A 4 on a final and a 4 semester mark each block gold."""
    rows = [row(MATH, 4, [("midterm", 5), ("final", 4)])]
    gold = by_kind(HonoursRules(), rows)["gold_medal"]
    results = {r.rule: r for r in gold.rules}
    assert not gold.eligible
    assert [(b.type, b.value) for b in results["gold_controls_all_five"].blocking] == [
        ("final", 4)
    ]
    assert results["gold_semester_all_five"].blocking[0].type == "semester"


def test_silver_rules() -> None:
    """Silver: at most one 4 and, when enabled, all-five controls."""
    rules = replace(HonoursRules(), silver_controls_all_five=FlagRule(True))
    rows = [row(MATH, 4, [("final", 4)]), row(PHYS, 5)]
    silver = by_kind(rules, rows)["silver_medal"]
    results = {r.rule: r for r in silver.rules}
    assert results["silver_semester_max_fours"].passed
    assert not results["silver_controls_all_five"].passed
    assert not silver.eligible


def test_disabled_rules_are_skipped_and_empty_awards_omitted() -> None:
    """Disabled rules do not appear; an award without rules is left out."""
    rules = replace(
        HonoursRules(),
        red_diploma_max_fours=MaxFoursRule(False, 1),
        gold_controls_all_five=FlagRule(False),
        gold_semester_all_five=FlagRule(False),
        silver_semester_max_fours=MaxFoursRule(False, 1),
    )
    awards = by_kind(rules, [row(MATH, 3)])
    assert "red_diploma" not in awards
    assert [r.rule for r in awards["gold_medal"].rules] == ["medal_certificate"]
    assert awards["gold_medal"].eligible


def test_certificate_serial_match() -> None:
    """Serials compare case-insensitively after trimming; None never matches."""
    assert serial_matches(" tm-a ", ["TM-A", "TMA"])
    assert serial_matches("tma", ["TM-A", "TMA"])
    assert not serial_matches("AB", ["TM-A", "TMA"])
    assert not serial_matches(None, ["TM-A"])
    awards = by_kind(HonoursRules(), [row(MATH, 5)], serial="AB")
    assert not awards["gold_medal"].eligible
    assert awards["red_diploma"].eligible
