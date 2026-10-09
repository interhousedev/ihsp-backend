"""LMS-AI-STUDIO: the `course_plan` kind (options, schema, task, validation)."""

from typing import Any

from app.modules.notebooks.domain.artifacts.handler import ProcessedOutput
from app.modules.notebooks.domain.artifacts.kinds.course_plan import HANDLER
from app.modules.notebooks.domain.artifacts.registry import handler_for
from app.modules.notebooks.domain.enums import ArtifactKind
from app.modules.notebooks.domain.errors import InvalidOptionsError, OutputInvalidError
from app.shared.contracts.lms_blocks import CoursePlanInput
from tests.notebooks.unit.domain.pack_support import assert_strict, make_ctx, make_pack

import pytest

CTX = make_ctx(make_pack((4,), titles=("Biology 10",)))


def step(title: str, **extra: Any) -> dict[str, Any]:
    """A valid planned step citing the first passage."""
    return {
        "title": title,
        "goals": [f"Explain {title.lower()}"],
        "summary": f"Covers {title.lower()}, practised with an example.",
        "refs": ["S1:P1"],
        **extra,
    }


def section(title: str, *steps: dict[str, Any], **extra: Any) -> dict[str, Any]:
    """A valid planned section."""
    return {
        "title": title,
        "goals": [f"Describe {title.lower()}"],
        "refs": ["S1:P2"],
        "steps": list(steps) or [step(f"{title} basics")],
        **extra,
    }


def document(*sections: dict[str, Any], **extra: Any) -> dict[str, Any]:
    """A valid model document."""
    return {
        "title": "Photosynthesis",
        "summary": "A short course.",
        "goals": ["Explain photosynthesis"],
        "sections": list(sections) or [section("Light")],
        **extra,
    }


def run(data: dict[str, Any], **options: Any) -> ProcessedOutput:
    parsed = HANDLER.parse_options(options)
    return HANDLER.process(data, parsed, CTX)


def test_the_kind_is_registered_with_its_handler() -> None:
    """LMS-AI-STUDIO: the registry finds the plan handler."""
    assert handler_for(ArtifactKind.COURSE_PLAN) is HANDLER
    assert HANDLER.schema_name == "nb_course_plan"


def test_default_options_are_stored_without_empty_values() -> None:
    """LMS-AI-STUDIO: depth defaults to overview, a blank focus is dropped."""
    stored = HANDLER.stored_options(HANDLER.parse_options({"focus": "  "}))

    assert stored == {"depth": "overview"}


def test_options_keep_depth_focus_and_the_section_hint() -> None:
    """LMS-AI-STUDIO: the design's options."""
    stored = HANDLER.stored_options(
        HANDLER.parse_options(
            {"depth": "detailed", "focus": " Light stage ", "sections_hint": 5}
        )
    )

    assert stored == {"depth": "detailed", "focus": "Light stage", "sections_hint": 5}


@pytest.mark.parametrize(
    "options",
    [
        {"depth": "huge"},
        {"sections_hint": 0},
        {"sections_hint": 31},
        {"focus": "x" * 201},
    ],
)
def test_bad_options_are_refused(options: dict[str, Any]) -> None:
    """LMS-AI-STUDIO: invalid options are `InvalidOptionsError`."""
    with pytest.raises(InvalidOptionsError):
        HANDLER.parse_options(options)


def test_more_tokens_are_given_to_a_detailed_plan() -> None:
    """LMS-AI-STUDIO: the output budget follows the depth."""
    overview = HANDLER.max_tokens(HANDLER.parse_options({}))
    detailed = HANDLER.max_tokens(HANDLER.parse_options({"depth": "detailed"}))

    assert overview < detailed


def test_strict_schema_requires_every_property() -> None:
    """LMS-AI-STUDIO: structured output needs a strict, self-contained schema."""
    assert_strict(HANDLER.strict_schema())


def test_task_block_follows_the_depth_and_the_hint() -> None:
    """LMS-AI-STUDIO: the task carries the sizes of the chosen depth and the focus."""
    options = HANDLER.parse_options(
        {"depth": "detailed", "sections_hint": 7, "focus": "Light stage"}
    )

    task = HANDLER.task_block(options, "for grade 10")

    assert "about 7 sections" in task
    assert "4 to 10 steps" in task
    assert "«Light stage»" in task
    assert "«for grade 10»" in task


def test_default_title_names_the_notebook() -> None:
    """LMS-AI-STUDIO: shown while the plan is generated."""
    assert HANDLER.default_title("Biology 10", HANDLER.parse_options({})) == (
        "Course plan: Biology 10"
    )


def test_a_valid_plan_is_stored_with_its_refs_and_language() -> None:
    """LMS-AI-STUDIO: the content is the contract's plan plus refs and language."""
    result = run(document(section("Light", step("Photons"), step("Pigments"))))

    content = result.content
    assert result.title == "Photosynthesis"
    assert content["language"] == "en"
    assert content["sections"][0]["steps"][1]["title"] == "Pigments"
    assert content["sections"][0]["steps"][0]["refs"] == ["S1:P1"]
    assert set(result.refs_index) == {"S1:P1", "S1:P2"}
    CoursePlanInput.model_validate(content)


def test_numbering_and_labels_are_removed_from_titles_and_texts() -> None:
    """LMS-AI-STUDIO: the LMS numbers sections itself; no S1:P1 reaches the plan."""
    result = run(
        document(
            section(
                "1. Light stage",
                step(
                    "Step 1: Photons [S1:P1]", summary="Photons carry energy [S1:P1]."
                ),
            )
        )
    )

    first = result.content["sections"][0]
    assert first["title"] == "Light stage"
    assert first["steps"][0]["title"] == "Photons"
    assert first["steps"][0]["summary"] == "Photons carry energy."


def test_unknown_refs_are_dropped_not_fatal() -> None:
    """LMS-AI-STUDIO: a plan without valid refs is still a plan."""
    result = run(document(section("Light", step("Photons", refs=["S9:P9"]))))

    assert result.content["sections"][0]["steps"][0]["refs"] == []


def test_duplicate_steps_and_sections_are_merged() -> None:
    """LMS-AI-STUDIO: the same title twice is one step (the LMS matches by title)."""
    result = run(
        document(
            section("Light", step("Photons"), step("photons "), step("Pigments")),
            section("LIGHT", step("Other")),
        )
    )

    sections = result.content["sections"]
    assert len(sections) == 1
    assert [s["title"] for s in sections[0]["steps"]] == ["Photons", "Pigments"]


def test_a_broken_step_is_dropped_and_the_rest_is_kept() -> None:
    """LMS-AI-STUDIO: per-step validation, like the other kinds."""
    broken = {"summary": "no title"}

    result = run(document(section("Light", step("Photons"), broken)))

    assert [s["title"] for s in result.content["sections"][0]["steps"]] == ["Photons"]


def test_a_section_without_a_usable_step_is_dropped() -> None:
    """LMS-AI-STUDIO: an empty section cannot be created in the LMS."""
    empty = {"title": "Empty", "goals": [], "refs": [], "steps": [{"summary": "x"}]}

    result = run(document(empty, section("Light")))

    assert [s["title"] for s in result.content["sections"]] == ["Light"]


def test_a_plan_without_any_valid_section_asks_for_a_repair() -> None:
    """LMS-AI-STUDIO: the problems name the section and the field."""
    with pytest.raises(OutputInvalidError) as caught:
        run(document({"title": "Empty", "steps": []}, {"steps": [step("x")]}))

    problems = " ".join(caught.value.problems)
    assert "section 1" in problems and "section 2" in problems


def test_sections_must_be_a_list() -> None:
    """LMS-AI-STUDIO: a document without sections is unusable."""
    with pytest.raises(OutputInvalidError):
        run({"title": "x", "sections": "none"})


def test_long_texts_are_cut_to_the_contract_limits() -> None:
    """LMS-AI-STUDIO: the plan always fits `CoursePlanInput`."""
    long_goals = [f"Goal number {n} " + "x" * 400 for n in range(12)]
    result = run(
        document(
            section("Light", step("Photons", goals=long_goals, summary="y" * 3000)),
            goals=long_goals,
        )
    )

    plan = CoursePlanInput.model_validate(result.content)
    assert len(plan.goals) == 10
    assert len(plan.sections[0].steps[0].goals) == 6
    assert len(plan.sections[0].steps[0].summary) <= 1200


def test_the_title_falls_back_to_the_first_source() -> None:
    """LMS-AI-STUDIO: a missing model title never leaves the artifact unnamed."""
    result = run(document(title=""))

    assert result.title == "Biology 10"
