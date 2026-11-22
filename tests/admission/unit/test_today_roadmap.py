"""The Today roadmap: one current node, grade-aware order; creative practice themes."""

from app.modules.admission.domain.essay_flow import (
    CREATIVE_THEMES,
    PRACTICE_THEMES,
    practice_prompt,
)
from app.modules.admission.domain.today import Snapshot, roadmap


def test_empty_student_starts_at_the_first_node() -> None:
    nodes = roadmap(Snapshot())
    assert nodes[0].state == "current"
    assert [n.state for n in nodes].count("current") == 1
    assert all(n.state == "locked" for n in nodes[1:])


def test_done_nodes_stay_behind_and_the_first_open_one_is_current() -> None:
    snap = Snapshot(countries_answered=True, major_chosen=True, list_size=6)
    nodes = roadmap(snap)
    states = {n.key: n.state for n in nodes}
    assert states["countries"] == states["major"] == states["list"] == "done"
    current = [n for n in nodes if n.state == "current"]
    assert len(current) == 1 and current[0].key == "tests"
    assert current[0].progress == "0/2"


def test_grade_ten_builds_the_profile_before_the_list() -> None:
    ten = [n.key for n in roadmap(Snapshot(grade="grade_10"))]
    eleven = [n.key for n in roadmap(Snapshot(grade="grade_11"))]
    assert ten.index("activities") < ten.index("list")
    assert eleven.index("list") < eleven.index("activities")


def test_creative_prompts_do_not_rotate_with_the_daily_themes() -> None:
    assert not set(CREATIVE_THEMES) & set(PRACTICE_THEMES)
    assert {"my_day", "essay_idea"} <= set(CREATIVE_THEMES)
    assert practice_prompt("my_day") == CREATIVE_THEMES["my_day"]
    assert practice_prompt("kitchen") == PRACTICE_THEMES["kitchen"]
