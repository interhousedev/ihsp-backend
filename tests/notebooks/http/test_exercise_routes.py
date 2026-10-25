"""HTTP: the exercise kind and POST .../exercise-feedback (AI feedback on an essay)."""

from typing import Any
from uuid import UUID

from app.modules.notebooks.domain.entities import Notebook, Source
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.modules.notebooks.wiring import NotebooksServices
from app.shared.actor import Actor
from tests.factories.notebooks import make_notebook, make_source
from tests.notebooks.unit.studio.helpers import SOURCE_TEXTS

import pytest
from httpx import AsyncClient

ESSAY = " ".join(["Technology changes how students learn every single day."] * 4)


@pytest.fixture
async def notebook(uow_factory: UowFactory, student: Actor) -> Notebook:
    """A notebook of the student."""
    return await make_notebook(uow_factory, student.user_id, title="English")


@pytest.fixture
async def source(uow_factory: UowFactory, notebook: Notebook) -> Source:
    """A ready, selected source."""
    return await make_source(uow_factory, notebook, title="Essay", texts=SOURCE_TEXTS)


async def _exercise(
    api: AsyncClient, services: NotebooksServices, notebook: Notebook, skill: str
) -> dict[str, Any]:
    base = f"/v1/notebooks/{notebook.id}/artifacts"
    body = {"kind": "exercise", "options": {"exam": "ielts_academic", "skill": skill}}
    created = await api.post(base, json=body)
    assert created.status_code == 202, created.text
    await services.generate_artifact.execute(UUID(created.json()["id"]))
    opened = await api.get(f"{base}/{created.json()['id']}")
    assert opened.status_code == 200, opened.text
    detail: dict[str, Any] = opened.json()
    return detail


def _questions(detail: dict[str, Any]) -> list[dict[str, Any]]:
    return [q for s in detail["content"]["sections"] for q in s["questions"]]


async def test_a_writing_exercise_has_an_essay_and_gets_feedback(
    api: AsyncClient, services: NotebooksServices, notebook: Notebook, source: Source
) -> None:
    detail = await _exercise(api, services, notebook, "writing")
    assert detail["status"] == "ready"
    essay = next(q for q in _questions(detail) if q["type"] == "free_response")
    assert essay["criteria"] and essay["min_words"] > 0

    url = f"/v1/notebooks/{notebook.id}/artifacts/{detail['id']}/exercise-feedback"
    response = await api.post(url, json={"question_id": essay["id"], "answer": ESSAY})

    assert response.status_code == 200, response.text
    feedback = response.json()
    assert set(feedback) == {
        "overall",
        "estimated_band",
        "criteria",
        "strengths",
        "improvements",
    }
    assert feedback["criteria"][0]["band"]


async def test_feedback_needs_an_essay_question_and_a_real_answer(
    api: AsyncClient, services: NotebooksServices, notebook: Notebook, source: Source
) -> None:
    detail = await _exercise(api, services, notebook, "reading")
    objective = _questions(detail)[0]
    url = f"/v1/notebooks/{notebook.id}/artifacts/{detail['id']}/exercise-feedback"

    wrong_type = await api.post(
        url, json={"question_id": objective["id"], "answer": ESSAY}
    )
    too_short = await api.post(
        url, json={"question_id": objective["id"], "answer": "short"}
    )

    assert wrong_type.status_code == 422
    assert too_short.status_code == 422


async def test_exercise_progress_is_saved(
    api: AsyncClient, services: NotebooksServices, notebook: Notebook, source: Source
) -> None:
    detail = await _exercise(api, services, notebook, "reading")
    url = f"/v1/notebooks/{notebook.id}/artifacts/{detail['id']}/progress"

    response = await api.put(url, json={"state": {"answers": {"q1": "A"}}})

    assert response.status_code == 204
