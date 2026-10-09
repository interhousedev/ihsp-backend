"""The course author assistant's instructions and course context."""

from datetime import date
from uuid import UUID

from app.modules.ai.domain.prompts_author import (
    AUTHOR_MARKER,
    CONTEXT_HEADING,
    CONTEXT_MAX_CHARS,
    author_system_prompt,
    course_context,
)
from app.modules.ai.infrastructure.fake_author import author_answer
from app.shared.contracts.lms import CourseBrief, CourseSectionBrief, CourseStepBrief
from app.shared.ids import new_id

import pytest

TODAY = date(2026, 10, 9)


def brief(sections: int = 1, steps: int = 2, title: str = "Limits") -> CourseBrief:
    """A course outline with numbered sections and steps."""
    return CourseBrief(
        course_id=new_id(),
        title="Calculus",
        description="Limits  and\nderivatives.",
        draft_seq=4,
        sections=tuple(
            CourseSectionBrief(
                section_id=f"s{n}",
                title=f"{title} {n}",
                steps=tuple(
                    CourseStepBrief(step_id=new_id(), title=f"Step {n}.{m}")
                    for m in range(1, steps + 1)
                ),
            )
            for n in range(1, sections + 1)
        ),
    )


def test_the_head_is_fixed_and_the_context_comes_last() -> None:
    """Same locale and date give the same head; the context is appended at the end."""
    context = course_context(brief())
    text = author_system_prompt("ru", TODAY, context)

    assert text.startswith("# ROLE\n" + AUTHOR_MARKER)
    assert text.endswith(context)
    assert author_system_prompt("ru", TODAY) == text.split("\n\n" + CONTEXT_HEADING)[0]
    assert "if unclear, in Russian" in text and "Today is 2026-10-09" in text


@pytest.mark.parametrize(
    "rule",
    [
        "PROPOSE BEFORE WRITING",
        "call search_workspace",
        "Never invent sources",
        "draft-conflict",
        "content-invalid",
        "You cannot publish, delete or reorder",
        "untrusted_data",
        "$...$ inline",
    ],
)
def test_the_instructions_cover_the_workflow(rule: str) -> None:
    """Grounding, proposals, error recovery, safety and formatting are spelled out."""
    assert rule in author_system_prompt("en", TODAY)


def test_the_context_lists_ids_in_order() -> None:
    """Sections and steps come numbered with their ids; whitespace is folded."""
    outline = brief(sections=2, steps=1)
    text = course_context(outline)
    step = outline.sections[1].steps[0]

    assert "Description: Limits and derivatives." in text
    assert "Draft outline (draft_seq 4):" in text
    assert "2. [section s2] Limits 2" in text
    assert f"   2.1 [step {step.step_id}] Step 2.1" in text


def test_empty_and_missing_courses_say_so() -> None:
    """An empty outline and a course that cannot be loaded are explicit."""
    empty = CourseBrief(UUID(int=1), "New", "", 1)

    assert "(empty: no sections yet)" in course_context(empty)
    assert "Description: (none)" in course_context(empty)
    assert "Call get_course_outline" in course_context(None)


def test_a_long_outline_is_cut_with_a_note() -> None:
    """Past the limit the outline stops at a whole line and asks for the tool."""
    text = course_context(brief(sections=30, steps=30, title="x" * 60))

    assert len(text) <= CONTEXT_MAX_CHARS + 80
    assert text.endswith("(shortened: call get_course_outline for the full outline)")


def test_the_fake_model_writes_into_the_first_step_of_the_context() -> None:
    """Development without a key: keywords pick a scripted tool call."""
    outline = brief()
    system = author_system_prompt("en", TODAY, course_context(outline))
    first = str(outline.sections[0].steps[0].step_id)

    _, test = author_answer(system, "Make a test about limits")
    _, plan = author_answer(system, "Propose a course plan")
    _, step = author_answer(system, "add a step on continuity")
    text, none = author_answer(system, "hello")

    assert test[0]["name"] == "add_test_block"
    assert test[0]["arguments"]["step_id"] == first
    assert plan[0]["name"] == "apply_outline"
    assert step[0]["arguments"]["section_id"] == "s1"
    assert none == [] and text.startswith("(fake author) hello")
