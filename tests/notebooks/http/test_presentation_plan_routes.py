"""HTTP: /v1/notebooks/{id}/presentation-plans* (PLAN)."""

from typing import Any

from app.modules.notebooks.domain.entities import Notebook, Source
from app.modules.notebooks.domain.presentation_plan import PLAN_MAX_SLIDES
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.shared.actor import Actor
from tests.factories.notebooks import make_notebook, make_source
from tests.notebooks.unit.studio.helpers import SOURCE_TEXTS

import pytest
from httpx import AsyncClient

PLAN_KEYS = {
    "id",
    "notebook_id",
    "title",
    "slides",
    "status",
    "max_slides",
    "over_limit",
    "artifact_id",
    "created_at",
    "updated_at",
}


@pytest.fixture
async def notebook(uow_factory: UowFactory, student: Actor) -> Notebook:
    """A notebook of the student."""
    return await make_notebook(uow_factory, student.user_id, title="Biology")


@pytest.fixture
async def source(uow_factory: UowFactory, notebook: Notebook) -> Source:
    """A ready, selected source."""
    return await make_source(
        uow_factory, notebook, title="Biology 10", texts=SOURCE_TEXTS
    )


def plans(notebook: Notebook) -> str:
    """The plans path of a notebook."""
    return f"/v1/notebooks/{notebook.id}/presentation-plans"


async def created(api: AsyncClient, notebook: Notebook) -> dict[str, Any]:
    """POST a plan and return it."""
    response = await api.post(plans(notebook), json={"prompt": "cells"})
    assert response.status_code == 201, response.text
    plan: dict[str, Any] = response.json()
    return plan


async def test_create_edit_and_confirm(
    api: AsyncClient, notebook: Notebook, source: Source
) -> None:
    """PLAN: outline first, edits saved, Generate queues the deck."""
    plan = await created(api, notebook)
    assert set(plan) == PLAN_KEYS
    assert plan["status"] == "draft"
    assert plan["max_slides"] == PLAN_MAX_SLIDES
    assert plan["slides"] and all(s["title"] for s in plan["slides"])

    slides = list(reversed(plan["slides"]))[:4]
    url = f"{plans(notebook)}/{plan['id']}"
    edited = await api.patch(url, json={"title": "Cells", "slides": slides})
    assert edited.status_code == 200, edited.text
    assert edited.json()["title"] == "Cells"
    assert [s["title"] for s in edited.json()["slides"]] == [s["title"] for s in slides]
    assert (await api.get(url)).json()["slides"] == edited.json()["slides"]

    confirmed = await api.post(f"{url}/confirm")
    assert confirmed.status_code == 202, confirmed.text
    body = confirmed.json()
    assert body["plan"]["status"] == "confirmed"
    assert body["artifact"]["kind"] == "slides"
    assert body["plan"]["artifact_id"] == body["artifact"]["id"]
    again = await api.post(f"{url}/confirm")
    assert again.status_code == 409
    assert again.json()["type"] == "notebooks/plan-confirmed"


async def test_a_plan_over_the_limit_is_refused_with_the_numbers(
    api: AsyncClient, notebook: Notebook, source: Source
) -> None:
    """PLAN: Generate answers 422 `plan-too-long` until the plan is trimmed."""
    plan = await created(api, notebook)
    url = f"{plans(notebook)}/{plan['id']}"
    long = [{"title": f"S{n}", "bullets": ["a"]} for n in range(PLAN_MAX_SLIDES + 1)]
    saved = await api.patch(url, json={"slides": long})
    assert saved.json()["over_limit"] is True

    refused = await api.post(f"{url}/confirm")

    assert refused.status_code == 422
    problem = refused.json()
    assert problem["type"] == "notebooks/plan-too-long"


async def test_another_students_plan_is_404(
    api: AsyncClient, notebook: Notebook, source: Source, uow_factory: UowFactory
) -> None:
    """PLAN: an unknown plan id answers 404."""
    response = await api.get(f"{plans(notebook)}/00000000-0000-7000-8000-000000000000")
    assert response.status_code == 404
