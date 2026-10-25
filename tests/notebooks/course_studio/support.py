"""Stored contents of ready course outputs, as the handlers write them."""

from typing import Any

from app.modules.notebooks.domain.entities import Artifact, Notebook
from app.modules.notebooks.domain.enums import ArtifactKind
from app.modules.notebooks.ports.unit_of_work import UowFactory
from tests.factories.notebooks import make_artifact

PLAN: dict[str, Any] = {
    "title": "Photosynthesis",
    "language": "en",
    "summary": "A short course.",
    "goals": ["Explain photosynthesis"],
    "sections": [
        {
            "title": "Light reactions",
            "goals": ["Describe the light stage"],
            "refs": ["S1:P1"],
            "steps": [
                {
                    "title": "Photons",
                    "goals": ["Explain photons"],
                    "summary": "Photons carry energy.",
                    "refs": [],
                },
                {
                    "title": "Pigments",
                    "goals": ["Name the pigments"],
                    "summary": "Chlorophyll absorbs light.",
                    "refs": [],
                },
            ],
        },
        {
            "title": "Calvin cycle",
            "goals": [],
            "refs": [],
            "steps": [
                {"title": "Carbon fixation", "goals": [], "summary": "", "refs": []}
            ],
        },
    ],
}

LESSON: dict[str, Any] = {
    "title": "Light reactions",
    "language": "en",
    "notes": ["test question 3 was dropped: a single choice question needs ..."],
    "blocks": [
        {
            "type": "text",
            "markdown": (
                "### Goal\n\nExplain the light stage.\n\n### Summary\n\n- Oxygen."
            ),
            "refs": ["S1:P2"],
        },
        {
            "type": "flashcards",
            "cards": [{"front": "Where?", "back": "Thylakoids."}],
            "refs": [],
        },
    ],
}

QUIZ: dict[str, Any] = {
    "title": "Quiz",
    "questions": [
        {
            "id": "q1",
            "type": "single",
            "prompt": "Which gas is released?",
            "options": [{"id": "a", "text": "Oxygen"}, {"id": "b", "text": "Argon"}],
            "correct": ["a"],
            "explanation": "Water is split.",
            "refs": ["S1:P2"],
        },
        {
            "id": "q2",
            "type": "true_false",
            "prompt": "Chlorophyll is green.",
            "options": [
                {"id": "true", "text": "True"},
                {"id": "false", "text": "False"},
            ],
            "correct": ["true"],
            "explanation": "It reflects green.",
            "refs": [],
        },
    ],
}

DECK: dict[str, Any] = {
    "title": "Cards",
    "cards": [
        {"id": "c1", "front": "Pigment?", "back": "Chlorophyll", "refs": ["S1:P4"]},
    ],
}


async def ready(
    uow_factory: UowFactory,
    notebook: Notebook,
    kind: ArtifactKind,
    content: dict[str, Any],
    **fields: Any,
) -> Artifact:
    """Store a ready output with the given content."""
    return await make_artifact(
        uow_factory, notebook, kind, content=content, title="Output", **fields
    )
