"""NB-14: exercises are profiled, written per section and checked per stimulus."""

from typing import Any

from app.modules.notebooks.application.assessment_pipeline import (
    AssessmentJob,
    AssessmentPipeline,
)
from app.modules.notebooks.application.llm import JsonCompletion
from app.modules.notebooks.domain.artifacts.handler import ProcessContext
from app.modules.notebooks.domain.artifacts.registry import handler_for
from app.modules.notebooks.domain.context import ContextPack
from app.modules.notebooks.domain.enums import ArtifactKind
from app.modules.notebooks.domain.tokens import Usage
from app.settings import Settings
from app.shared.ai_tasks import AiTask

PASSAGE = (
    "A Urban trees cool cities. Their leaves shade streets and release water "
    "vapour, which lowers the air temperature on hot afternoons.\n\n"
    "B Planting is cheap, but young trees need watering for three to five years. "
    "Schemes that hire local residents keep far more saplings alive."
)


def tfng(prompt: str, answer: str) -> dict[str, Any]:
    return {
        "id": "",
        "type": "true_false_not_given",
        "prompt": prompt,
        "options": [],
        "correct": [answer],
        "items": [],
        "accepted": [],
        "word_limit": 0,
        "min_words": 0,
        "time_minutes": 0,
        "criteria": [],
        "model_outline": [],
        "explanation": "Paragraph A says so.",
        "refs": [],
    }


def gap(prompt: str, answer: str) -> dict[str, Any]:
    return {**tfng(prompt, ""), "type": "gap_fill", "correct": [], "accepted": [answer]}


def essay() -> dict[str, Any]:
    criteria = [
        {
            "name": "Task Response",
            "description": "Answers every part of the task.",
            "bands": [{"band": "7", "descriptor": "A clear position throughout."}],
        }
    ]
    return {
        **tfng("Some people think cities should plant more trees. Discuss.", ""),
        "type": "free_response",
        "correct": [],
        "min_words": 250,
        "time_minutes": 40,
        "criteria": criteria,
        "model_outline": ["Position", "Two reasons", "Conclusion"],
    }


def section(stimulus: str, questions: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "title": "Exercise",
        "instructions": "Read and answer.",
        "rubric": [],
        "sections": [
            {"title": "Urban trees", "stimulus": stimulus, "questions": questions}
        ],
    }


class ScriptedAsk:
    """Answers per task; records every request's last message."""

    def __init__(self, writes: list[dict[str, Any]], verdicts: list[Any]) -> None:
        self.writes = writes
        self.verdicts = verdicts
        self.calls: list[tuple[AiTask, str]] = []

    async def __call__(
        self,
        task: AiTask,
        system: str,
        messages: list[dict[str, Any]],
        schema_name: str,
        schema: dict[str, Any],
        max_tokens: int,
    ) -> JsonCompletion:
        self.calls.append((task, str(messages[-1]["content"])))
        if task is AiTask.STUDIO_SOURCE_PROFILE:
            data: dict[str, Any] = {"sources": []}
        elif task is AiTask.STUDIO_ITEM_VERIFY:
            data = {"verdicts": self.verdicts.pop(0)}
        else:
            data = self.writes.pop(0)
        return JsonCompletion(data=data, text="", usage=Usage(), model="fake")


class FakeNotebookLlm:
    def max_tokens(self, task: AiTask, default: int) -> int:
        return default


def job(options: dict[str, Any]) -> AssessmentJob:
    handler = handler_for(ArtifactKind.EXERCISE)
    pack = ContextPack(sources=(), mode="full", token_estimate=0)
    return AssessmentJob(
        task=AiTask.STUDIO_EXERCISE,
        cards=False,
        handler=handler,
        options=handler.parse_options(options),
        ctx=ProcessContext(pack, "en", 1),
        system="system",
        context={"role": "user", "content": "<sources/>"},
        samples={"S1": "Notes about urban trees and heat."},
        prompt="ielts reading practice",
        count=3,
        types=("card",),
        difficulty="medium",
        mode=None,
    )


def pipeline(settings: Settings) -> AssessmentPipeline:
    llm: Any = FakeNotebookLlm()
    return AssessmentPipeline(llm, settings)


def verdict(qid: str, answer: list[str]) -> dict[str, Any]:
    return {
        "id": qid,
        "self_contained": True,
        "answer": answer,
        "single_answer": True,
        "reason": "",
    }


async def test_a_reading_section_is_checked_with_its_own_stimulus_only(
    settings: Settings,
) -> None:
    questions = [
        tfng("Leaves shade streets.", "true"),
        tfng("Young trees need no water.", "false"),
        gap("Young trees need watering for ____ to five years.", "three"),
    ]
    ask = ScriptedAsk(
        [section(PASSAGE, questions)],
        [[verdict("q1", ["true"]), verdict("q2", ["not_given"]), verdict("q3", [])]],
    )
    options = {"exam": "ielts_academic", "skill": "reading", "count": 3}
    out = await pipeline(settings).run(job(options), ask)
    tasks = [task for task, _ in ask.calls]
    assert tasks == [
        AiTask.STUDIO_SOURCE_PROFILE,
        AiTask.STUDIO_EXERCISE,
        AiTask.STUDIO_ITEM_VERIFY,
    ]
    verify = ask.calls[2][1]
    assert "<stimulus>" in verify and "Notes about urban trees" not in verify
    prompts = [q["prompt"] for q in out.content["sections"][0]["questions"]]
    assert prompts == [questions[0]["prompt"], questions[2]["prompt"]]
    assert out.content["blueprint"]["rejected"] == 1
    assert "Write exactly one entry of `sections`" in ask.calls[1][1]


async def test_a_section_without_its_passage_is_written_again(
    settings: Settings,
) -> None:
    questions = [tfng("Leaves shade streets.", "true")]
    ask = ScriptedAsk(
        [section("", questions), section(PASSAGE, questions)],
        [[verdict("q1", ["true"])]],
    )
    options = {"exam": "ielts_academic", "skill": "reading", "count": 1}
    out = await pipeline(settings).run(job(options), ask)
    assert len(out.content["sections"]) == 1
    assert "rejected for" in ask.calls[2][1]


async def test_a_writing_task_skips_the_solver(settings: Settings) -> None:
    prompt = "Write about the role of trees in cities (at least 250 words)."
    ask = ScriptedAsk([section(prompt, [essay()])], [])
    options = {"exam": "ielts_academic", "skill": "writing"}
    out = await pipeline(settings).run(job(options), ask)
    question = out.content["sections"][0]["questions"][0]
    assert question["type"] == "free_response" and question["criteria"]
    assert AiTask.STUDIO_ITEM_VERIFY not in [task for task, _ in ask.calls]
