"""HTTP: topic labels under /v1/notebooks/{id} (spec 3.4, G12/G13)."""

from typing import Any
from app.modules.notebooks.domain.entities import Notebook, Source
from app.modules.notebooks.domain.labels import LabelOrigin
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.shared.actor import Actor
from app.shared.ids import new_id
from tests.factories.notebooks import make_notebook, make_source
from tests.fakes.notebooks.llm import ScriptedLlm
from tests.fakes.tasks import FakeTaskKicker
from tests.notebooks.unit.labels.support import answer, store_label, store_link

import pytest
from httpx import AsyncClient, Response

LABEL_KEYS = {"id", "name", "emoji", "position", "origin", "source_count"}
AUTO_KEYS = {"status", "finished_at", "error"}


def problem_type(response: Response) -> str:
    """The `type` of a problem+json response."""
    assert response.headers["content-type"].startswith("application/problem+json")
    return str(response.json()["type"])


@pytest.fixture
async def notebook(uow_factory: UowFactory, student: Actor) -> Notebook:
    """A notebook of the student."""
    return await make_notebook(uow_factory, student.user_id, title="Biology")


@pytest.fixture
async def theirs(uow_factory: UowFactory, other_student: Actor) -> Notebook:
    """A notebook of the other student."""
    return await make_notebook(uow_factory, other_student.user_id)


@pytest.fixture
async def source(uow_factory: UowFactory, notebook: Notebook) -> Source:
    """A ready, selected source."""
    return await make_source(uow_factory, notebook, title="Cells")


def url(notebook: Notebook, suffix: str = "") -> str:
    """`/v1/notebooks/{id}/labels` plus a suffix."""
    return f"/v1/notebooks/{notebook.id}/labels{suffix}"


# - - - List - - -


async def test_an_empty_notebook_lists_no_labels_and_an_idle_auto_state(
    api: AsyncClient, notebook: Notebook
) -> None:
    """G12: `{items: [], auto: {status: idle, finished_at: null}}`."""
    response = await api.get(url(notebook))

    assert response.status_code == 200, response.text
    assert response.json() == {
        "items": [],
        "auto": {"status": "idle", "finished_at": None, "error": None},
    }


async def test_the_list_has_the_label_item_shape_and_the_source_count(
    api: AsyncClient, uow_factory: UowFactory, notebook: Notebook, source: Source
) -> None:
    """G12: LabelItem keys, by position."""
    cells = await store_label(uow_factory, notebook.id, "Cells", position=1)
    await store_label(uow_factory, notebook.id, "Energy", LabelOrigin.AUTO, 2)
    await store_link(uow_factory, source.id, cells.id)

    body = (await api.get(url(notebook))).json()

    assert set(body["auto"]) == AUTO_KEYS
    assert all(set(item) == LABEL_KEYS for item in body["items"])
    assert [(i["name"], i["origin"], i["source_count"]) for i in body["items"]] == [
        ("Cells", "manual", 1),
        ("Energy", "auto", 0),
    ]


async def test_the_labels_of_another_students_notebook_are_a_404(
    api: AsyncClient, theirs: Notebook
) -> None:
    """G12: the same `notebooks/not-found` as for any foreign notebook."""
    response = await api.get(url(theirs))

    assert response.status_code == 404
    assert problem_type(response) == "notebooks/not-found"


# - - - Create, update, delete - - -


async def test_post_makes_a_manual_label(api: AsyncClient, notebook: Notebook) -> None:
    """G12: `201 LabelItem`, origin manual, next position."""
    response = await api.post(url(notebook), json={"name": " Cells ", "emoji": "🧬"})

    assert response.status_code == 201, response.text
    body = response.json()
    assert set(body) == LABEL_KEYS
    assert (body["name"], body["emoji"], body["origin"], body["position"]) == (
        "Cells",
        "🧬",
        "manual",
        1,
    )
    assert body["source_count"] == 0


@pytest.mark.parametrize(
    "body",
    [{}, {"name": ""}, {"name": "x" * 41}, {"name": "Cells", "emoji": "e" * 9}],
)
async def test_post_validates_the_name_and_the_emoji(
    api: AsyncClient, notebook: Notebook, body: dict[str, Any]
) -> None:
    """G12: 422."""
    response = await api.post(url(notebook), json=body)

    assert response.status_code == 422


async def test_post_a_blank_name_is_a_typed_error(
    api: AsyncClient, notebook: Notebook
) -> None:
    """G12: spaces only is `notebooks/invalid-options`."""
    response = await api.post(url(notebook), json={"name": "   ", "emoji": ""})

    assert response.status_code == 422
    assert problem_type(response) == "notebooks/invalid-options"


async def test_post_a_duplicate_name_is_a_409(
    api: AsyncClient, notebook: Notebook
) -> None:
    """G12: `notebooks/label-duplicate`."""
    await api.post(url(notebook), json={"name": "Cells", "emoji": "🧬"})

    response = await api.post(url(notebook), json={"name": "cells", "emoji": "🧬"})

    assert response.status_code == 409
    assert problem_type(response) == "notebooks/label-duplicate"


async def test_post_the_thirteenth_label_is_a_409(
    api: AsyncClient, notebook: Notebook
) -> None:
    """G12: `notebooks/labels-limit`, with the i18n key and its parameters."""
    for n in range(12):
        await api.post(url(notebook), json={"name": f"Topic {n}", "emoji": "🧬"})

    response = await api.post(url(notebook), json={"name": "More", "emoji": "🧬"})

    assert response.status_code == 409
    assert problem_type(response) == "notebooks/labels-limit"
    body = response.json()
    assert body["message_key"] == "notebooks-labels-limit"
    assert body["params"] == {"limit": 12, "per_source": 3}


async def test_post_to_a_foreign_notebook_is_a_404(
    api: AsyncClient, theirs: Notebook
) -> None:
    """G12: `notebooks/not-found`."""
    response = await api.post(url(theirs), json={"name": "Cells", "emoji": "🧬"})

    assert response.status_code == 404


async def test_patch_edits_and_an_auto_label_becomes_manual(
    api: AsyncClient, uow_factory: UowFactory, notebook: Notebook
) -> None:
    """G12: partial body, `origin: manual` afterwards."""
    auto = await store_label(uow_factory, notebook.id, "Cells", LabelOrigin.AUTO)

    response = await api.patch(url(notebook, f"/{auto.id}"), json={"emoji": "🦠"})

    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["name"], body["emoji"], body["origin"]) == ("Cells", "🦠", "manual")


async def test_patch_errors_are_typed(
    api: AsyncClient, uow_factory: UowFactory, notebook: Notebook
) -> None:
    """G12: duplicate 409, unknown label 404."""
    await store_label(uow_factory, notebook.id, "Cells", position=1)
    energy = await store_label(uow_factory, notebook.id, "Energy", position=2)

    duplicate = await api.patch(url(notebook, f"/{energy.id}"), json={"name": "cells"})
    missing = await api.patch(url(notebook, f"/{new_id()}"), json={"name": "A"})

    assert (duplicate.status_code, problem_type(duplicate)) == (
        409,
        "notebooks/label-duplicate",
    )
    assert (missing.status_code, problem_type(missing)) == (
        404,
        "notebooks/label-not-found",
    )


async def test_delete_answers_204_and_the_label_is_gone(
    api: AsyncClient, uow_factory: UowFactory, notebook: Notebook
) -> None:
    """G12: `204`, then a second delete is a 404."""
    label = await store_label(uow_factory, notebook.id, "Cells")

    first = await api.delete(url(notebook, f"/{label.id}"))
    again = await api.delete(url(notebook, f"/{label.id}"))
    listed = await api.get(url(notebook))

    assert (first.status_code, first.content) == (204, b"")
    assert (again.status_code, problem_type(again)) == (404, "notebooks/label-not-found")
    assert listed.json()["items"] == []


async def test_a_foreign_notebooks_label_cannot_be_changed_through_mine(
    api: AsyncClient, uow_factory: UowFactory, notebook: Notebook, theirs: Notebook
) -> None:
    """G12: a label id of another notebook is `label-not-found`."""
    label = await store_label(uow_factory, theirs.id, "Theirs")

    patched = await api.patch(url(notebook, f"/{label.id}"), json={"name": "Mine"})
    deleted = await api.delete(url(notebook, f"/{label.id}"))

    assert [patched.status_code, deleted.status_code] == [404, 404]


# - - - Labels of a source - - -


def source_url(notebook: Notebook, source: Source) -> str:
    """`PUT /v1/notebooks/{id}/sources/{sid}/labels`."""
    return f"/v1/notebooks/{notebook.id}/sources/{source.id}/labels"


async def test_put_replaces_the_labels_of_a_source_and_returns_the_item(
    api: AsyncClient, uow_factory: UowFactory, notebook: Notebook, source: Source
) -> None:
    """G12: the updated SourceItem with `label_ids`; the lists agree."""
    cells = await store_label(uow_factory, notebook.id, "Cells", position=1)
    energy = await store_label(uow_factory, notebook.id, "Energy", position=2)

    response = await api.put(
        source_url(notebook, source), json={"label_ids": [str(energy.id), str(cells.id)]}
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["id"] == str(source.id)
    assert sorted(body["label_ids"]) == sorted([str(cells.id), str(energy.id)])
    listed = (await api.get(f"/v1/notebooks/{notebook.id}/sources")).json()
    assert listed[0]["label_ids"] == body["label_ids"]
    detail = (await api.get(f"/v1/notebooks/{notebook.id}/sources/{source.id}")).json()
    assert detail["label_ids"] == body["label_ids"]
    counts = (await api.get(url(notebook))).json()["items"]
    assert [i["source_count"] for i in counts] == [1, 1]


async def test_put_with_no_labels_clears_the_source(
    api: AsyncClient, uow_factory: UowFactory, notebook: Notebook, source: Source
) -> None:
    """G12: an empty list."""
    cells = await store_label(uow_factory, notebook.id, "Cells")
    await store_link(uow_factory, source.id, cells.id)

    response = await api.put(source_url(notebook, source), json={"label_ids": []})

    assert response.json()["label_ids"] == []


async def test_put_refuses_four_labels_and_foreign_ones(
    api: AsyncClient,
    uow_factory: UowFactory,
    notebook: Notebook,
    theirs: Notebook,
    source: Source,
) -> None:
    """G12: `labels-limit` 409; a label of another notebook is 404."""
    made = [
        await store_label(uow_factory, notebook.id, f"T{n}", position=n)
        for n in range(4)
    ]
    foreign = await store_label(uow_factory, theirs.id, "Theirs")

    four = await api.put(
        source_url(notebook, source), json={"label_ids": [str(x.id) for x in made]}
    )
    other = await api.put(
        source_url(notebook, source), json={"label_ids": [str(foreign.id)]}
    )

    assert (four.status_code, problem_type(four)) == (409, "notebooks/labels-limit")
    assert (other.status_code, problem_type(other)) == (
        404,
        "notebooks/label-not-found",
    )


async def test_put_on_a_foreign_source_is_a_404(
    api: AsyncClient, uow_factory: UowFactory, theirs: Notebook
) -> None:
    """G12: `notebooks/not-found`."""
    their_source = await make_source(uow_factory, theirs)

    response = await api.put(
        f"/v1/notebooks/{theirs.id}/sources/{their_source.id}/labels",
        json={"label_ids": []},
    )

    assert response.status_code == 404


async def test_the_put_route_is_not_shadowed_by_the_source_routes(
    api: AsyncClient, notebook: Notebook, source: Source
) -> None:
    """G12: PUT .../labels reaches the labels use case; the source route has no PUT."""
    put = await api.put(source_url(notebook, source), json={"label_ids": []})
    wrong = await api.put(
        f"/v1/notebooks/{notebook.id}/sources/{source.id}", json={"label_ids": []}
    )

    assert (put.status_code, wrong.status_code) == (200, 405)


# - - - Auto labels - - -


async def test_auto_answers_202_running_and_queues_the_job(
    api: AsyncClient, kicker: FakeTaskKicker, notebook: Notebook, source: Source
) -> None:
    """G13: `202 {status: running}`, one `notebooks.label_sources` job."""
    response = await api.post(url(notebook, "/auto"), json={})

    assert response.status_code == 202, response.text
    assert response.json() == {"status": "running"}
    assert kicker.calls == [
        ("notebooks.label_sources", {"notebook_id": str(notebook.id)})
    ]
    state = (await api.get(url(notebook))).json()["auto"]
    assert state["status"] == "running"


async def test_auto_without_a_body_works_too(
    api: AsyncClient, notebook: Notebook, source: Source
) -> None:
    """G13: the body is optional."""
    response = await api.post(url(notebook, "/auto"))

    assert response.status_code == 202


async def test_auto_while_running_is_a_409(
    api: AsyncClient, notebook: Notebook, source: Source
) -> None:
    """G13: `notebooks/labels-running`."""
    await api.post(url(notebook, "/auto"))

    response = await api.post(url(notebook, "/auto"))

    assert response.status_code == 409
    assert problem_type(response) == "notebooks/labels-running"


async def test_auto_without_a_selected_ready_source_is_a_422(
    api: AsyncClient, notebook: Notebook
) -> None:
    """G13: `notebooks/labels-nothing-to-label`."""
    response = await api.post(url(notebook, "/auto"))

    assert response.status_code == 422
    assert problem_type(response) == "notebooks/labels-nothing-to-label"
    assert response.json()["message_key"] == "notebooks-labels-nothing-to-label"


async def test_auto_on_a_foreign_notebook_is_a_404(
    api: AsyncClient, theirs: Notebook
) -> None:
    """G13: `notebooks/not-found`."""
    response = await api.post(url(theirs, "/auto"))

    assert response.status_code == 404


async def test_the_whole_flow_from_click_to_labels(
    api: AsyncClient,
    services: Any,
    scripted_llm: ScriptedLlm,
    notebook: Notebook,
    source: Source,
) -> None:
    """G13: click, job runs, the list shows auto labels, the source has label ids."""
    scripted_llm.queue_json(answer([("Cells", "🧬")], {"s1": ["l1"]}))
    await api.post(url(notebook, "/auto"))

    await services.label_sources.execute(notebook.id)

    body = (await api.get(url(notebook))).json()
    assert body["auto"]["status"] == "idle" and body["auto"]["finished_at"] is not None
    [item] = body["items"]
    assert (item["name"], item["origin"], item["source_count"]) == ("Cells", "auto", 1)
    sources = (await api.get(f"/v1/notebooks/{notebook.id}/sources")).json()
    assert sources[0]["label_ids"] == [item["id"]]


async def test_a_failed_run_is_listed_with_its_reason(
    api: AsyncClient,
    services: Any,
    scripted_llm: ScriptedLlm,
    notebook: Notebook,
    source: Source,
) -> None:
    """G13: `failed` / `invalid-output`, no labels, and a new run may start."""
    scripted_llm.queue_json({"labels": [], "assignments": []})
    await api.post(url(notebook, "/auto"))
    await services.label_sources.execute(notebook.id)

    body = (await api.get(url(notebook))).json()
    again = await api.post(url(notebook, "/auto"))

    assert body["items"] == []
    assert body["auto"]["status"] == "failed" and body["auto"]["error"] == "invalid-output"
    assert again.status_code == 202

