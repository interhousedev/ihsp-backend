"""NB-14: quizzes and flash cards are planned, written in batches and checked."""

from typing import Any

from app.modules.notebooks.domain.entities import Notebook, Source
from app.modules.notebooks.domain.enums import ArtifactKind, ArtifactStatus
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.shared.actor import Actor
from app.shared.ai_tasks import AiTask
from tests.notebooks.unit.studio.helpers import Build, HookedLlm, generate

PROFILE = {
    "sources": [
        {
            "label": "S1",
            "kind": "reading_passages",
            "subject": "Biology",
            "domains": ["photosynthesis"],
            "item_pools": ["passages"],
            "has_math": False,
            "term_definition_pairs": False,
        }
    ]
}
EXCERPT = "Chlorophyll absorbs red and blue light and reflects green light."


def question(spec_id: str, prompt: str, stimulus: str = "") -> dict[str, Any]:
    return {
        "spec_id": spec_id,
        "stimulus": stimulus,
        "type": "single",
        "prompt": prompt,
        "options": [
            {"id": "a", "text": "Green light"},
            {"id": "b", "text": "Red light"},
            {"id": "c", "text": "Blue light"},
            {"id": "d", "text": "Ultraviolet light"},
        ],
        "correct": ["a"],
        "explanation": "Chlorophyll reflects green light, so leaves look green.",
        "hint": "",
        "difficulty": "medium",
        "topic": "Pigments",
        "refs": ["S1:P4"],
    }


def ok(*ids: str) -> dict[str, Any]:
    return {
        "verdicts": [
            {
                "id": i,
                "self_contained": True,
                "answer": [],
                "single_answer": True,
                "reason": "",
            }
            for i in ids
        ]
    }


def tasks(llm: HookedLlm) -> list[str]:
    return [request["tuning"].task for request in llm.json_requests]


async def test_unseen_passage_item_is_rejected_and_the_slot_rewritten(
    build: Build,
    student: Actor,
    notebook: Notebook,
    source: Source,
    uow_factory: UowFactory,
    scripted_llm: HookedLlm,
) -> None:
    """NB-14: a stem without its excerpt is dropped; the fill round writes it again."""
    studio = build()
    scripted_llm.queue_json(PROFILE)
    scripted_llm.queue_json({"items": []})
    scripted_llm.queue_json(
        {
            "title": "Pigments",
            "questions": [
                question("b1", "Which light does chlorophyll reflect?", EXCERPT),
                question("b2", "According to the text, which light is reflected?"),
            ],
        }
    )
    scripted_llm.queue_json(ok("b1"))
    scripted_llm.queue_json(
        {
            "title": "",
            "questions": [
                question("b2", "Which colour do leaves reflect most?", EXCERPT)
            ],
        }
    )
    scripted_llm.queue_json(ok("b2"))

    artifact = await generate(
        studio,
        uow_factory,
        student,
        notebook,
        ArtifactKind.QUIZ,
        {"count": 2, "types": ["single"], "mode": "reading_test"},
    )

    assert artifact.status is ArtifactStatus.READY
    content = artifact.content or {}
    questions = content["questions"]
    assert [q["id"] for q in questions] == ["q1", "q2"]
    assert all(q["prompt"].startswith(f"> {EXCERPT}") for q in questions)
    blueprint = content["blueprint"]
    assert (blueprint["mode"], blueprint["requested"]) == ("reading_test", 2)
    assert (blueprint["delivered"], blueprint["rejected"]) == (2, 1)
    assert tasks(scripted_llm) == [
        AiTask.STUDIO_SOURCE_PROFILE.value,
        AiTask.STUDIO_ASSESSMENT_PLAN.value,
        AiTask.STUDIO_QUIZ.value,
        AiTask.STUDIO_ITEM_VERIFY.value,
        AiTask.STUDIO_QUIZ.value,
        AiTask.STUDIO_ITEM_VERIFY.value,
    ]
    refill = scripted_llm.json_requests[4]["messages"][-1]["content"]
    assert "- b2:" in refill and "- b1:" not in refill


async def test_the_solver_rejects_an_ambiguous_item(
    build: Build,
    student: Actor,
    notebook: Notebook,
    source: Source,
    uow_factory: UowFactory,
    scripted_llm: HookedLlm,
) -> None:
    """NB-14: an item with no single defensible key is not delivered."""
    studio = build(notebooks={"assessment_fill_rounds": 0})
    scripted_llm.queue_json(PROFILE)
    scripted_llm.queue_json({"items": []})
    scripted_llm.queue_json(
        {
            "title": "Pigments",
            "questions": [
                question("b1", "Which light does chlorophyll reflect?"),
                question("b2", "Which colour do leaves reflect most?"),
            ],
        }
    )
    verdicts = ok("b1", "b2")
    verdicts["verdicts"][1]["single_answer"] = False
    scripted_llm.queue_json(verdicts)

    artifact = await generate(
        studio,
        uow_factory,
        student,
        notebook,
        ArtifactKind.QUIZ,
        {"count": 2, "types": ["single"], "mode": "concept_check"},
    )

    content = artifact.content or {}
    assert len(content["questions"]) == 1
    assert content["blueprint"]["rejected"] == 1


async def test_vocab_cards_get_the_vocab_mode_and_the_exact_count(
    build: Build,
    student: Actor,
    notebook: Notebook,
    source: Source,
    uow_factory: UowFactory,
    scripted_llm: HookedLlm,
) -> None:
    """NB-14: a vocabulary-list profile picks the vocab mode; one card per slot."""
    studio = build()
    profile = {"sources": [{**PROFILE["sources"][0], "kind": "vocabulary_list"}]}
    scripted_llm.queue_json(profile)
    scripted_llm.queue_json({"items": []})
    scripted_llm.queue_json(
        {
            "title": "Words",
            "cards": [
                {
                    "spec_id": f"b{n}",
                    "front": f"word{n}",
                    "back": f"meaning number {n}",
                    "hint": "",
                    "topic": "Words",
                    "refs": [],
                }
                for n in range(1, 4)
            ],
        }
    )
    scripted_llm.queue_json(ok("b1", "b2", "b3"))

    artifact = await generate(
        studio, uow_factory, student, notebook, ArtifactKind.FLASHCARDS, {"count": 3}
    )

    content = artifact.content or {}
    assert content["blueprint"]["mode"] == "vocab_test"
    assert [c["front"] for c in content["cards"]] == ["word1", "word2", "word3"]
