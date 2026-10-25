"""NB-14: exam quotas, the template swap round, source copies and Studio OpenUI."""

from collections import Counter
from dataclasses import replace
from typing import Any

from app.modules.notebooks.application.assessment_pipeline import (
    AssessmentJob,
    AssessmentPipeline,
)
from app.modules.notebooks.application.llm import JsonCompletion
from app.modules.notebooks.domain.artifacts.handler import ProcessContext
from app.modules.notebooks.domain.artifacts.registry import handler_for
from app.modules.notebooks.domain.assessment.blueprint import (
    PlanItemOut,
    build_blueprint,
    rules_for,
    swap_template,
)
from app.modules.notebooks.domain.assessment.exams import EXAMS, exam_for, quotas
from app.modules.notebooks.domain.assessment.items import (
    copied_source,
    source_items,
    stimulus_words,
)
from app.modules.notebooks.domain.assessment.modes import MODE_SPECS
from app.modules.notebooks.domain.assessment.profile import SourceProfile
from app.modules.notebooks.domain.context import ContextPack
from app.modules.notebooks.domain.enums import ArtifactKind
from app.modules.notebooks.domain.tokens import Usage
from app.settings import Settings
from app.settings_ai import AiSettings
from app.shared.ai_tasks import AiTask
from app.shared.openui.finalize import OpenUiFinalizer

import pytest

MATH = (
    "SAT Math practice\n\n"
    "1. If $3x + 7 = 22$, what is the value of $x$? Answer: 5\n"
    "2. A right triangle has legs 6 and 8. What is the hypotenuse? Answer: 10\n"
)
TABLE = (
    "```openui\n"
    'root = Table(["Year", "Share"], [["2000", 20], ["2020", 80]])\n'
    "```"
)
BROKEN = "```openui\nroot = Nope(1)\n```"
PROBLEM = SourceProfile(label="S1", kind="problem_set", subject="SAT Math")


# - - - Fakes - - -


class FakeNotebookLlm:
    """Only `max_tokens` is used by the pipeline itself."""

    def max_tokens(self, task: AiTask, default: int) -> int:
        return default


class ScriptedAsk:
    """Answers each task from its own queue; the planner and solver stay quiet."""

    def __init__(self, batches: list[list[dict[str, Any]]]) -> None:
        self.batches = batches
        self.tasks: list[str] = []

    async def __call__(
        self,
        task: AiTask,
        system: str,
        messages: list[dict[str, Any]],
        schema_name: str,
        schema: dict[str, Any],
        max_tokens: int,
    ) -> JsonCompletion:
        self.tasks.append(str(messages[-1]["content"]))
        if task is AiTask.STUDIO_SOURCE_PROFILE:
            data: dict[str, Any] = {"sources": []}
        elif task is AiTask.STUDIO_ASSESSMENT_PLAN:
            data = {"items": []}
        elif task is AiTask.STUDIO_ITEM_VERIFY:
            data = {"verdicts": []}
        else:
            data = {"title": "Quiz", "questions": self.batches.pop(0)}
        return JsonCompletion(data=data, text="", usage=Usage(), model="fake")


class FakeRepairLlm:
    """The OPENUI_REPAIR call: always answers with a block that is still broken."""

    def __init__(self) -> None:
        self.calls = 0

    async def complete(self, **request: Any) -> dict[str, Any]:
        self.calls += 1
        return {"text": BROKEN}


def question(prompt: str, explanation: str = "Because $3x = 15$.") -> dict[str, Any]:
    return {
        "spec_id": "b1",
        "stimulus": "",
        "type": "single",
        "prompt": prompt,
        "options": [
            {"id": "a", "text": "5"},
            {"id": "b", "text": "6"},
            {"id": "c", "text": "7"},
            {"id": "d", "text": "8"},
        ],
        "correct": ["a"],
        "explanation": explanation,
        "hint": "",
        "difficulty": "medium",
        "topic": "Algebra",
        "refs": [],
    }


def job(prompt: str | None = None, mode: str = "problem_practice") -> AssessmentJob:
    handler = handler_for(ArtifactKind.QUIZ)
    options = handler.parse_options({"count": 1, "types": ["single"]})
    pack = ContextPack(sources=(), mode="full", token_estimate=0)
    return AssessmentJob(
        task=AiTask.STUDIO_QUIZ,
        cards=False,
        handler=handler,
        options=options,
        ctx=ProcessContext(pack, "en", 1),
        system="system",
        context={"role": "user", "content": "<sources/>"},
        samples={"S1": MATH},
        prompt=prompt,
        count=1,
        types=("single",),
        difficulty="medium",
        mode=mode,
    )


def pipeline(
    settings: Settings, rounds: int = 1, openui: OpenUiFinalizer | None = None
) -> AssessmentPipeline:
    notebooks = settings.notebooks.model_copy(
        update={"assessment_fill_rounds": rounds, "assessment_verify": False}
    )
    changed = settings.model_copy(update={"notebooks": notebooks})
    llm: Any = FakeNotebookLlm()
    return AssessmentPipeline(llm, changed, openui)


def studio_openui(llm: FakeRepairLlm) -> OpenUiFinalizer:
    profile = AiSettings().profile(AiTask.OPENUI_REPAIR)
    return OpenUiFinalizer(
        llm, profile, enabled=True, subset="studio"  # type: ignore[arg-type]
    )


# - - - Exam quotas - - -


def test_a_sat_mock_splits_sections_and_math_domains_by_the_official_weights() -> None:
    exam = exam_for("full_mock", "Full SAT mock", [])
    assert exam is not None
    table = quotas(exam, 44)
    counts = {q.domain: q.count for q in table}
    sections = Counter[str]()
    for q in table:
        sections[q.section] += q.count
    assert sum(counts.values()) == 44
    assert sections == {"Reading and Writing": 22, "Math": 22}
    assert counts["Algebra"] == counts["Advanced Math"] == 8
    assert counts["Problem-Solving and Data Analysis"] == 3
    assert counts["Geometry and Trigonometry"] == 3


def test_quotas_apply_only_to_a_mock_of_a_known_exam() -> None:
    reading = SourceProfile(label="S2", kind="reading_passages")
    assert exam_for("topic_test", "SAT algebra", [PROBLEM]) is None
    assert exam_for("topic_test", "make me a sat test", [PROBLEM, reading])
    assert exam_for("concept_check", "make me a sat test", [PROBLEM, reading]) is None
    assert exam_for("full_mock", "Biology mock", []) is None
    assert exam_for("full_mock", None, [PROBLEM]) == EXAMS[0]


def test_the_blueprint_keeps_every_quota_and_maps_planner_domains() -> None:
    table = quotas(EXAMS[0], 20)
    rules = rules_for(
        count=20,
        types=["single"],
        spec=MODE_SPECS["concept_check"],
        cards=False,
        difficulty="medium",
        labels=["S1"],
        quotas=table,
    )
    planned = [
        PlanItemOut(
            template="direct_computation",
            domain="Linear equations",
            difficulty="easy",
            source="S1",
            focus="3x + 7 = 22",
        )
    ] * 30  # far too many algebra slots: the quota caps them
    blueprint = build_blueprint(rules, [PROBLEM], planned)
    got = Counter(spec.domain for spec in blueprint)
    assert got == {q.domain: q.count for q in table}
    reading = [s for s in blueprint if s.domain == "Information and Ideas"]
    assert reading and all(s.stimulus for s in reading)
    assert not any(s.stimulus for s in blueprint if s.domain == "Algebra")


def test_a_swap_keeps_the_domain_and_takes_another_template() -> None:
    table = quotas(EXAMS[0], 10)
    rules = rules_for(
        count=10,
        types=["single"],
        spec=MODE_SPECS["concept_check"],
        cards=False,
        difficulty="medium",
        labels=["S1"],
        quotas=table,
    )
    spec = next(s for s in build_blueprint(rules, [PROBLEM]) if s.domain == "Algebra")
    swapped = swap_template(rules, spec)
    assert swapped is not None
    assert swapped.domain == "Algebra" and swapped.template != spec.template
    assert swapped.template in MODE_SPECS["problem_practice"].quiz_templates


# - - - Source copies - - -


def test_a_copy_of_a_source_problem_is_detected_but_new_numbers_pass() -> None:
    pool = source_items([MATH])
    assert copied_source("If $3x + 7 = 22$, what is the value of $x$?", pool)
    assert copied_source(
        "A right triangle has legs 6 and 8. Find the hypotenuse.", pool
    )
    assert copied_source("If $3x + 7 = 25$, what is the value of $x$?", pool) is None
    assert copied_source("What is the main idea of the text?", pool) is None


async def test_a_copied_item_is_rewritten_with_new_numbers(settings: Settings) -> None:
    ask = ScriptedAsk(
        [
            [question("If $3x + 7 = 22$, what is the value of $x$?")],
            [question("If $3x + 2 = 17$, what is the value of $x$?")],
        ]
    )
    out = await pipeline(settings).run(job(), ask)
    assert out.content["questions"][0]["prompt"].startswith("If $3x + 2 = 17$")
    assert "copies a source problem" in ask.tasks[-1]


async def test_a_source_review_request_may_repeat_the_source_problems(
    settings: Settings,
) -> None:
    ask = ScriptedAsk([[question("If $3x + 7 = 22$, what is the value of $x$?")]])
    out = await pipeline(settings).run(job("Quiz me on the same problems"), ask)
    assert out.content["questions"][0]["prompt"].startswith("If $3x + 7 = 22$")


# - - - The swap round - - -


async def test_a_slot_failing_all_rounds_gets_one_more_try_with_another_template(
    settings: Settings,
) -> None:
    unseen = question("According to the text, what is $x$ if $2x = 10$?")
    ask = ScriptedAsk(
        [[unseen], [unseen], [question("If $2x + 1 = 11$, what is the value of $x$?")]]
    )
    out = await pipeline(settings, rounds=1).run(job(), ask)
    blueprint = out.content["blueprint"]
    assert blueprint["delivered"] == 1
    first = MODE_SPECS["problem_practice"].quiz_templates[0]
    assert blueprint["items"][0]["template"] != first
    assert "template=" + blueprint["items"][0]["template"] in ask.tasks[-1]


# - - - OpenUI in Studio - - -


def test_a_visual_block_does_not_count_against_the_stimulus_words() -> None:
    assert stimulus_words(f"Shares of households online.\n{TABLE}") == 4


async def test_openui_blocks_are_kept_when_valid_and_dropped_when_broken(
    settings: Settings,
) -> None:
    repair = FakeRepairLlm()
    explanation = f"The share rose from 20 to 80.\n\n{TABLE}\n\n{BROKEN}"
    ask = ScriptedAsk(
        [[question("If $2x + 1 = 11$, what is $x$?", explanation=explanation)]]
    )
    out = await pipeline(settings, openui=studio_openui(repair)).run(job(), ask)
    stored = out.content["questions"][0]["explanation"]
    assert TABLE in stored
    assert "Nope" not in stored
    assert repair.calls == 1
    assert "```openui" in ask.tasks[2]  # the batch task teaches the blocks


async def test_blocks_are_removed_when_studio_openui_is_off(settings: Settings) -> None:
    explanation = f"The share rose from 20 to 80.\n\n{TABLE}"
    ask = ScriptedAsk(
        [[question("If $2x + 1 = 11$, what is $x$?", explanation=explanation)]]
    )
    out = await pipeline(settings).run(job(), ask)
    assert "openui" not in out.content["questions"][0]["explanation"]
    assert "```openui" not in ask.tasks[2]


@pytest.mark.parametrize("enabled", [True, False])
def test_the_pipeline_keeps_only_an_enabled_finalizer(
    settings: Settings, enabled: bool
) -> None:
    profile = AiSettings().profile(AiTask.OPENUI_REPAIR)
    llm: Any = FakeRepairLlm()
    finalizer = OpenUiFinalizer(llm, profile, enabled=enabled, subset="studio")
    assert (pipeline(settings, openui=finalizer).openui is not None) is enabled


async def test_a_copied_source_passage_is_rejected_under_a_new_stem(
    settings: Settings,
) -> None:
    passage = (
        "The collection of letters written by the explorer ______ now held in the "
        "national archive."
    )
    copied = {**question("Which verb form correctly completes the sentence?")}
    copied["stimulus"] = passage
    fresh = {**copied, "stimulus": "The notebooks of two botanists ______ on display."}
    ask = ScriptedAsk([[copied], [fresh]])
    rw = replace(job(), samples={"S1": f"Practice 5\n{passage}"})
    out = await pipeline(settings).run(rw, ask)
    assert "botanists" in out.content["questions"][0]["prompt"]
    assert "copies a source problem" in ask.tasks[-1]


def test_a_source_passage_reused_under_another_question_is_a_copy() -> None:
    practice = (
        "Practice 1 (Craft and Structure)\n"
        "Text: Urban beekeepers in Lisbon once struggled to keep colonies alive "
        "through hot summers.\n"
        "Which choice completes the text with the most logical word?\n"
        "A) cumbersome B) pragmatic\n"
        "Answer: B"
    )
    pool = source_items([practice])
    stimulus = (
        "Urban beekeepers in Lisbon once struggled to keep colonies alive "
        "through hot summers."
    )
    assert copied_source(stimulus, pool)


def test_a_generic_source_question_is_not_a_copy_target() -> None:
    practice = (
        "Practice 2\nText: Historians assumed that medieval farmers rarely "
        "traveled far from home, but new evidence suggests otherwise.\n"
        "Which choice best states the main idea of the text?\nAnswer: B"
    )
    pool = source_items([practice])
    assert (
        copied_source("Which choice best states the main idea of the text?", pool)
        is None
    )
