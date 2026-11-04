"""NB-FC: POST /v1/notebooks/flashcard-workspace."""

from app.shared.actor import Actor
from app.shared.ids import new_id
from tests.fakes.ai.contracts import make_file
from tests.fakes.notebooks.world import World

from httpx import AsyncClient

URL = "/v1/notebooks/flashcard-workspace"


async def test_a_file_gives_the_hidden_notebook_and_a_pending_source(
    api: AsyncClient, world: World, student: Actor
) -> None:
    """NB-FC: the response names the notebook; the list does not show it."""
    ref = world.files.add_text(make_file(student.user_id, name="a.pdf"), "text")

    response = await api.post(URL, json={"file_ids": [str(ref.id)]})

    assert response.status_code == 200, response.text
    body = response.json()
    assert [s["status"] for s in body["sources"]] == ["pending"]
    listed = (await api.get("/v1/notebooks")).json()["items"]
    assert body["notebook_id"] not in [item["id"] for item in listed]
    studio = await api.get(f"/v1/notebooks/{body['notebook_id']}/sources")
    assert studio.status_code == 200


async def test_a_foreign_notebook_is_a_404(api: AsyncClient) -> None:
    """NB-FC: IDOR on the route."""
    response = await api.post(
        URL,
        json={
            "notebook_sources": [
                {"notebook_id": str(new_id()), "source_id": str(new_id())}
            ]
        },
    )

    assert response.status_code == 404


async def test_too_many_files_are_a_422(api: AsyncClient) -> None:
    """NB-FC: the batch limit on the route."""
    response = await api.post(URL, json={"file_ids": [str(new_id())] * 21})

    assert response.status_code == 422


async def test_an_empty_request_is_refused(api: AsyncClient) -> None:
    """NB-FC: nothing chosen."""
    response = await api.post(URL, json={})

    assert response.status_code in (400, 422)
