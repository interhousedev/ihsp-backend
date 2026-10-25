"""Fake exercise and essay feedback documents (no language model, `fake` mode).

The demo passage names the topics of the passages in its own words, so it never
copies a source; every question is answerable from it.
"""

from collections.abc import Sequence
from typing import Any

from app.modules.ai.infrastructure.fake_sources import (
    FakePassage,
    document_passages,
    last_user_text,
)
from app.modules.ai.infrastructure.fake_structured import title_of, topic, unique

Document = dict[str, Any]
_LETTERS = "ABCDEF"
_CRITERIA = [
    {
        "name": "Task Response (TR)",
        "description": "How fully the answer addresses the task.",
        "bands": [
            {"band": "9", "descriptor": "Fully addresses every part of the task."},
            {"band": "6", "descriptor": "Addresses the task, some parts briefly."},
            {"band": "4", "descriptor": "Responds to the task only in part."},
        ],
    },
    {
        "name": "Coherence and Cohesion (CC)",
        "description": "How clearly the ideas are organised and linked.",
        "bands": [
            {"band": "9", "descriptor": "Ideas flow logically, paragraphs are clear."},
            {"band": "6", "descriptor": "Organised, with some faulty linking."},
            {"band": "4", "descriptor": "Little clear progression."},
        ],
    },
]


def _empty(kind: str, prompt: str) -> Document:
    return {
        "id": "",
        "type": kind,
        "prompt": prompt,
        "options": [],
        "correct": [],
        "items": [],
        "accepted": [],
        "word_limit": 0,
        "min_words": 0,
        "time_minutes": 0,
        "criteria": [],
        "model_outline": [],
        "explanation": "Demo content: see the paragraph named in the question.",
        "refs": [],
    }


def build_exercise(passages: Sequence[FakePassage], task: str) -> Document:
    """One section: a demo passage, a choice, a T/F/NG, a gap and maybe an essay."""
    topics = unique([topic(p.text) for p in passages])[:4]
    while len(topics) < 4:
        topics.append(f"Demo idea {len(topics) + 1}")
    paragraphs = [
        f"{_LETTERS[n]}. This demo paragraph is about {name.casefold()}."
        for n, name in enumerate(topics)
    ]
    labels = [p.label for p in passages if p.label][:1]
    choice = _empty("single_choice", "Which idea does paragraph A describe?")
    choice["options"] = [{"id": f"o{n}", "text": name} for n, name in enumerate(topics)]
    choice["correct"] = ["o0"]
    choice["refs"] = labels
    tfng = _empty("true_false_not_given", "The passage gives the year of each idea.")
    tfng["correct"] = ["not_given"]
    gap = _empty("gap_fill", "Paragraph B is about ____.")
    gap["accepted"] = [topics[1].casefold()]
    gap["word_limit"] = max(1, len(topics[1].split()))
    questions = [choice, tfng, gap]
    if "`writing`" in task or "`mixed`" in task:
        essay = _empty(
            "free_response", f"Write an essay: how important is {topics[0]}?"
        )
        essay.update(
            min_words=150,
            time_minutes=30,
            criteria=_CRITERIA,
            model_outline=["State a clear position.", "Give two examples."],
        )
        questions.append(essay)
    return {
        "title": f"{title_of(passages)}: demo exercise",
        "instructions": "Demo exercise without a language model. Read and answer.",
        "sections": [
            {
                "title": "Demo passage",
                "stimulus": "\n\n".join(paragraphs),
                "questions": questions,
            }
        ],
        "rubric": [],
    }


def build_exercise_feedback(_: Sequence[FakePassage], __: str) -> Document:
    """A fixed demo feedback with one score per criterion."""
    return {
        "overall": "Demo feedback without a language model.",
        "estimated_band": "6",
        "criteria": [
            {
                "name": "Task Response (TR)",
                "band": "6",
                "comment": "Demo: the answer addresses the task.",
            }
        ],
        "strengths": ["Demo: clear position."],
        "improvements": ["Demo: add a concrete example."],
    }


def build_exercise_document(
    schema_name: str, messages: Sequence[dict[str, Any]]
) -> Document | None:
    """The fake exercise or feedback document; None for any other schema."""
    if schema_name == "nb_exercise":
        return build_exercise(document_passages(messages), last_user_text(messages))
    if schema_name == "nb_exercise_feedback":
        return build_exercise_feedback([], "")
    return None
