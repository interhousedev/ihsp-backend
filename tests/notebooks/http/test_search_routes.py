"""HTTP: GET /v1/notebooks/{id}/search, the full-text search of the Sources panel."""

from typing import Any

from app.modules.notebooks.domain.entities import Notebook
from app.modules.notebooks.domain.enums import SourceKind, SourceStatus
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.shared.actor import Actor, Role
from app.shared.ids import new_id
from tests.factories.notebooks import make_notebook, make_source

import pytest
from httpx import AsyncClient, Response

RESULT_KEYS = {"query", "sources"}
SOURCE_KEYS = {"source_id", "title", "kind", "hits"}
HIT_KEYS = {"passage_id", "seq", "page", "snippet"}
PLANTS = (
    "Photosynthesis happens in the chloroplast of a leaf cell.",
    "Light reactions of photosynthesis split water and release oxygen.",
    "The Calvin cycle uses carbon dioxide to build sugar.",
    "Photosynthesis photosynthesis photosynthesis: the plant makes food.",
    "Stomata let a leaf take in carbon dioxide for photosynthesis.",
)


def problem_type(response: Response) -> str:
    """The `type` of a problem+json response (and check its media type)."""
    assert response.headers["content-type"].startswith("application/problem+json")
    return str(response.json()["type"])


@pytest.fixture
async def notebook(uow_factory: UowFactory, student: Actor) -> Notebook:
    """A notebook with a plants source and a source about cells."""
    notebook = await make_notebook(uow_factory, student.user_id, title="Biology")
    await make_source(uow_factory, notebook, texts=PLANTS, title="Plants")
    await make_source(
        uow_factory,
        notebook,
        kind=SourceKind.NOTE,
        texts=("Mitochondria release energy ⟦1⟧ for the cell ⟦w2⟧.",),
        title="Cells",
    )
    return notebook


def url(notebook: Notebook) -> str:
    """The search route of a notebook."""
    return f"/v1/notebooks/{notebook.id}/search"


async def test_search_returns_the_sources_with_their_hits(
    api: AsyncClient, notebook: Notebook
) -> None:
    """NB-14: `200` with query, then sources with id, title, kind and hits."""
    response = await api.get(url(notebook), params={"q": "photosynthesis"})

    body = response.json()
    assert response.status_code == 200, response.text
    assert set(body) == RESULT_KEYS and body["query"] == "photosynthesis"
    (plants,) = body["sources"]
    assert set(plants) == SOURCE_KEYS
    assert (plants["title"], plants["kind"]) == ("Plants", "text")
    assert len(plants["hits"]) == 3
    assert all(set(hit) == HIT_KEYS for hit in plants["hits"])
    assert plants["hits"][0]["seq"] == 4
    assert plants["hits"][0]["page"] is None
    assert all("hotosynthesis" in hit["snippet"] for hit in plants["hits"])


async def test_search_snippets_are_plain_text_without_citation_markers(
    api: AsyncClient, notebook: Notebook
) -> None:
    """NB-14: a note that kept `⟦1⟧` and `⟦w2⟧` shows clean words."""
    response = await api.get(url(notebook), params={"q": "mitochondria"})

    (cells,) = response.json()["sources"]
    assert cells["kind"] == "note"
    assert cells["hits"][0]["snippet"] == "Mitochondria release energy for the cell."


async def test_search_limit_caps_the_hits_in_total(
    api: AsyncClient, notebook: Notebook
) -> None:
    """NB-14: `limit=2` returns two hits of the best source."""
    response = await api.get(url(notebook), params={"q": "photosynthesis", "limit": 2})

    (plants,) = response.json()["sources"]
    assert len(plants["hits"]) == 2


async def test_search_ignores_sources_that_are_not_ready(
    api: AsyncClient, uow_factory: UowFactory, notebook: Notebook
) -> None:
    """NB-14: a failed source with passages is not searched."""
    await make_source(
        uow_factory,
        notebook,
        texts=("Photosynthesis in a failed source.",),
        status=SourceStatus.FAILED,
    )

    response = await api.get(url(notebook), params={"q": "failed"})

    assert response.json() == {"query": "failed", "sources": []}


async def test_search_with_no_match_is_an_empty_list(
    api: AsyncClient, notebook: Notebook
) -> None:
    """NB-14: nothing found is `200` with `sources: []`."""
    response = await api.get(url(notebook), params={"q": "zzzzzz"})

    assert response.status_code == 200
    assert response.json() == {"query": "zzzzzz", "sources": []}


async def test_another_students_notebook_is_a_404(
    api: AsyncClient, uow_factory: UowFactory, other_student: Actor
) -> None:
    """NB-15: the same `404` as for a missing notebook."""
    theirs = await make_notebook(uow_factory, other_student.user_id)
    await make_source(uow_factory, theirs, texts=("Secret light.",))

    foreign = await api.get(url(theirs), params={"q": "light"})
    missing = await api.get(f"/v1/notebooks/{new_id()}/search", params={"q": "light"})

    assert foreign.status_code == missing.status_code == 404
    assert problem_type(foreign) == problem_type(missing) == "notebooks/not-found"


@pytest.mark.parametrize(
    "params",
    [
        {},
        {"q": ""},
        {"q": "a"},
        {"q": "x" * 201},
        {"q": "light", "limit": 0},
        {"q": "light", "limit": 101},
        {"q": "light", "limit": "many"},
    ],
)
async def test_search_rejects_a_bad_query_string_with_422(
    api: AsyncClient, notebook: Notebook, params: dict[str, Any]
) -> None:
    """NB-14: `q` is 2 to 200 characters, `limit` 1 to 100."""
    response = await api.get(url(notebook), params=params)

    assert response.status_code == 422
    assert problem_type(response) == "common/request-validation"


async def test_search_refuses_a_query_that_is_blank_after_trimming(
    api: AsyncClient, notebook: Notebook
) -> None:
    """NB-14: two spaces are two characters for the schema but no request."""
    response = await api.get(url(notebook), params={"q": "  "})

    assert response.status_code == 422
    assert problem_type(response) == "notebooks/invalid-options"


async def test_search_accepts_the_edges_of_the_limits(
    api: AsyncClient, notebook: Notebook
) -> None:
    """NB-14: `q` of 2 and 200 characters, `limit` 1 and 100."""
    short = await api.get(url(notebook), params={"q": "ab", "limit": 1})
    long = await api.get(url(notebook), params={"q": "x" * 200, "limit": 100})

    assert short.status_code == long.status_code == 200


async def test_search_is_limited_to_30_a_minute(
    api: AsyncClient, notebook: Notebook
) -> None:
    """NB-14: the 31st search in a minute is a `429`."""
    for _ in range(30):
        assert (await api.get(url(notebook), params={"q": "light"})).status_code == 200

    response = await api.get(url(notebook), params={"q": "light"})

    assert response.status_code == 429
    assert problem_type(response) == "common/rate-limited"


@pytest.mark.parametrize("role", [Role.TEACHER, Role.ADMIN])
async def test_search_in_a_personal_notebook_is_for_its_owner_only(
    api: AsyncClient,
    current: dict[str, Actor],
    make_actor: Any,
    notebook: Notebook,
    role: Role,
) -> None:
    """NB-15: staff are not the owner, so a personal notebook is a `404` for them."""
    current["actor"] = make_actor(role)

    response = await api.get(url(notebook), params={"q": "photosynthesis"})

    assert response.status_code == 404
