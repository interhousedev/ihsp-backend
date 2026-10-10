"""HTTP: /v1/notebooks (list, create, open, edit, delete, usage), § 4.3 and § 4.4."""

from collections.abc import Callable
from typing import Any

from app.interfaces.http.dependencies import get_actor
from app.interfaces.http.v1.notebooks import ROUTERS
from app.modules.notebooks.domain.enums import SourceStatus
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.modules.notebooks.wiring import NotebooksServices
from app.settings import Settings
from app.shared.actor import Actor, Role
from app.shared.ids import new_id
from tests.factories.notebooks import make_notebook, make_source

import pytest
from httpx import AsyncClient, Response

ITEM_KEYS = {
    "id",
    "title",
    "emoji",
    "pinned",
    "source_count",
    "last_opened_at",
    "updated_at",
    "origin",
    "subject_id",
    "lesson_id",
    "course_id",
    "can_write",
}
DETAIL_KEYS = ITEM_KEYS | {
    "auto",
    "chat_config",
    "summary",
    "summary_status",
    "ready_source_count",
    "selected_source_count",
    "created_at",
}
CONFIG_KEYS = {"style", "custom_prompt", "length", "language", "goal"}
USAGE_PART_KEYS = {"used", "limit", "resets_at"}


def problem_type(response: Response) -> str:
    """The `type` of a problem+json response (and check its media type)."""
    assert response.headers["content-type"].startswith("application/problem+json")
    return str(response.json()["type"])


# - - - Create and open - - -


async def test_create_returns_a_notebook_detail_with_a_default_title(
    api: AsyncClient,
) -> None:
    """NB-1, NB-3: `201`, the exact NotebookDetail keys, the "Untitled" title."""
    response = await api.post("/v1/notebooks", json={})

    body = response.json()
    assert response.status_code == 201, response.text
    assert set(body) == DETAIL_KEYS
    assert set(body["chat_config"]) == CONFIG_KEYS
    assert body["title"] == "Untitled notebook"
    assert body["emoji"] is None and body["pinned"] is False
    assert body["chat_config"] == {
        "style": "default",
        "custom_prompt": None,
        "length": "default",
        "language": "auto",
        "goal": None,
    }
    assert body["summary"] is None and body["summary_status"] == "none"
    assert body["source_count"] == 0
    assert body["ready_source_count"] == 0 and body["selected_source_count"] == 0
    assert body["last_opened_at"] is not None


async def test_create_keeps_the_title_and_emoji_of_the_student(
    api: AsyncClient,
) -> None:
    """NB-3: a title and an emoji given at creation are stored as they are."""
    response = await api.post(
        "/v1/notebooks", json={"title": "  Biology 10  ", "emoji": "🧬"}
    )

    assert response.status_code == 201
    assert response.json()["title"] == "Biology 10"
    assert response.json()["emoji"] == "🧬"


@pytest.mark.parametrize(
    "body",
    [
        {"title": 5},
        {"title": "x" * 121},
        {"emoji": "x" * 17},
        {"emoji": ["🧬"]},
    ],
)
async def test_create_rejects_a_bad_body_with_422(
    api: AsyncClient, body: dict[str, Any]
) -> None:
    """NB-3: a body that does not fit the schema is a `422` problem+json."""
    response = await api.post("/v1/notebooks", json=body)

    assert response.status_code == 422
    assert problem_type(response) == "common/request-validation"


async def test_opening_a_notebook_returns_the_detail_with_source_counters(
    api: AsyncClient,
    uow_factory: UowFactory,
    student: Actor,
) -> None:
    """NB-3, NB-5: counters of ready and of selected-and-ready sources."""
    notebook = await make_notebook(uow_factory, student.user_id, title="Biology")
    await make_source(uow_factory, notebook, title="Ready, ticked")
    await make_source(uow_factory, notebook, title="Ready, off", selected=False)
    await make_source(
        uow_factory, notebook, title="Pending", texts=(), status=SourceStatus.PENDING
    )

    response = await api.get(f"/v1/notebooks/{notebook.id}")

    body = response.json()
    assert response.status_code == 200, response.text
    assert set(body) == DETAIL_KEYS
    assert body["id"] == str(notebook.id) and body["title"] == "Biology"
    assert body["source_count"] == 3
    assert body["ready_source_count"] == 2
    assert body["selected_source_count"] == 1
    assert body["last_opened_at"] is not None


# - - - List - - -


async def test_list_returns_pages_of_items_pinned_first(
    api: AsyncClient, uow_factory: UowFactory, student: Actor
) -> None:
    """NB-3: `Page<NotebookItem>`, pinned first, a cursor to the next page."""
    plain = [
        await make_notebook(uow_factory, student.user_id, title=f"Plain {n}")
        for n in range(2)
    ]
    pinned = await make_notebook(
        uow_factory, student.user_id, title="Pinned", pinned=True
    )

    first = (await api.get("/v1/notebooks", params={"limit": 2})).json()
    second = (
        await api.get(
            "/v1/notebooks", params={"limit": 2, "cursor": first["next_cursor"]}
        )
    ).json()

    assert set(first) == {"items", "next_cursor"}
    assert all(set(item) == ITEM_KEYS for item in first["items"] + second["items"])
    assert first["items"][0]["id"] == str(pinned.id)
    assert first["next_cursor"] is not None
    assert second["next_cursor"] is None
    listed = {item["id"] for item in first["items"] + second["items"]}
    assert listed == {str(pinned.id)} | {str(n.id) for n in plain}


async def test_list_filters_by_title_and_shows_only_the_students_own(
    api: AsyncClient,
    uow_factory: UowFactory,
    student: Actor,
    other_student: Actor,
) -> None:
    """NB-3, NB-15: `?q` is a title search; notebooks of others never appear."""
    mine = await make_notebook(uow_factory, student.user_id, title="Cell biology")
    await make_notebook(uow_factory, student.user_id, title="Algebra")
    await make_notebook(uow_factory, other_student.user_id, title="Biology of others")

    found = (await api.get("/v1/notebooks", params={"q": "biolog"})).json()
    everything = (await api.get("/v1/notebooks")).json()

    assert [item["id"] for item in found["items"]] == [str(mine.id)]
    assert len(everything["items"]) == 2
    assert everything["next_cursor"] is None


@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 101}, {"limit": "x"}])
async def test_list_rejects_a_bad_limit_with_422(
    api: AsyncClient, params: dict[str, Any]
) -> None:
    """NB-3: the page size is 1 to 100."""
    response = await api.get("/v1/notebooks", params=params)

    assert response.status_code == 422
    assert problem_type(response) == "common/request-validation"


async def test_list_rejects_a_broken_cursor_with_422(api: AsyncClient) -> None:
    """NB-3: a cursor that was not made by the server is a `422`."""
    response = await api.get("/v1/notebooks", params={"cursor": "not-a-cursor"})

    assert response.status_code == 422
    assert problem_type(response) == "common/validation"


# - - - Edit - - -


async def test_patch_changes_only_the_keys_that_were_sent(
    api: AsyncClient, uow_factory: UowFactory, student: Actor
) -> None:
    """NB-3: a key that is absent is kept; `emoji: null` is a real change."""
    notebook = await make_notebook(
        uow_factory, student.user_id, title="Biology", emoji="🧬"
    )
    url = f"/v1/notebooks/{notebook.id}"

    pinned = await api.patch(url, json={"pinned": True})
    renamed = await api.patch(url, json={"title": "Cell biology"})
    cleared = await api.patch(url, json={"emoji": None})
    untouched = await api.patch(url, json={})

    assert pinned.status_code == 200, pinned.text
    assert set(pinned.json()) == DETAIL_KEYS
    assert pinned.json()["pinned"] is True
    assert pinned.json()["title"] == "Biology" and pinned.json()["emoji"] == "🧬"
    assert renamed.json()["title"] == "Cell biology"
    assert renamed.json()["pinned"] is True and renamed.json()["emoji"] == "🧬"
    assert cleared.json()["emoji"] is None
    assert cleared.json()["title"] == "Cell biology"
    assert untouched.json() == cleared.json()


async def test_patch_merges_the_chat_settings_over_the_current_ones(
    api: AsyncClient, uow_factory: UowFactory, student: Actor
) -> None:
    """NB-7: `chat_config` may carry only the settings that change."""
    notebook = await make_notebook(uow_factory, student.user_id)
    url = f"/v1/notebooks/{notebook.id}"

    first = await api.patch(url, json={"chat_config": {"style": "learning_guide"}})
    second = await api.patch(
        url, json={"chat_config": {"length": "shorter", "language": "ru"}}
    )

    assert first.json()["chat_config"] == {
        "style": "learning_guide",
        "custom_prompt": None,
        "length": "default",
        "language": "auto",
        "goal": None,
    }
    assert second.json()["chat_config"] == {
        "style": "learning_guide",
        "custom_prompt": None,
        "length": "shorter",
        "language": "ru",
        "goal": None,
    }
    assert (await api.get(url)).json()["chat_config"] == second.json()["chat_config"]


async def test_patch_saves_the_goal_and_the_detail_returns_it(
    api: AsyncClient, uow_factory: UowFactory, student: Actor
) -> None:
    """NB-7: `chat_config.goal` round-trips; later settings keep it."""
    notebook = await make_notebook(uow_factory, student.user_id)
    url = f"/v1/notebooks/{notebook.id}"

    saved = await api.patch(
        url, json={"chat_config": {"goal": "  Pass the biology exam  "}}
    )
    later = await api.patch(url, json={"chat_config": {"length": "longer"}})

    assert saved.status_code == 200, saved.text
    assert saved.json()["chat_config"]["goal"] == "Pass the biology exam"
    assert later.json()["chat_config"]["goal"] == "Pass the biology exam"
    assert (await api.get(url)).json()["chat_config"]["goal"] == "Pass the biology exam"


@pytest.mark.parametrize("blank", ["", "   ", None])
async def test_patch_turns_a_blank_goal_into_null(
    api: AsyncClient, uow_factory: UowFactory, student: Actor, blank: str | None
) -> None:
    """NB-7: an empty goal clears it."""
    notebook = await make_notebook(uow_factory, student.user_id)
    url = f"/v1/notebooks/{notebook.id}"
    await api.patch(url, json={"chat_config": {"goal": "Pass the exam"}})

    cleared = await api.patch(url, json={"chat_config": {"goal": blank}})

    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["chat_config"]["goal"] is None
    assert (await api.get(url)).json()["chat_config"]["goal"] is None


@pytest.mark.parametrize(
    "body",
    [
        {"chat_config": {"style": "pirate"}},
        {"chat_config": {"custom_prompt": "x" * 1001}},
        {"chat_config": {"goal": "g" * 301}},
        {"chat_config": {"goal": 5}},
        {"pinned": "maybe"},
        {"title": "x" * 121},
    ],
)
async def test_patch_rejects_a_bad_body_with_422(
    api: AsyncClient,
    uow_factory: UowFactory,
    student: Actor,
    body: dict[str, Any],
) -> None:
    """NB-3, NB-7: values that do not fit the schema are a `422` problem+json."""
    notebook = await make_notebook(uow_factory, student.user_id)

    response = await api.patch(f"/v1/notebooks/{notebook.id}", json=body)

    assert response.status_code == 422
    assert problem_type(response) == "common/request-validation"


@pytest.mark.parametrize("body", [{"title": "   "}, {"title": None}, {"pinned": None}])
async def test_patch_refuses_a_value_the_use_case_does_not_allow(
    api: AsyncClient, uow_factory: UowFactory, student: Actor, body: dict[str, Any]
) -> None:
    """NB-3: a blank or null title, a null flag: `notebooks/invalid-options`."""
    notebook = await make_notebook(uow_factory, student.user_id, title="Biology")

    response = await api.patch(f"/v1/notebooks/{notebook.id}", json=body)

    assert response.status_code == 422
    assert problem_type(response) == "notebooks/invalid-options"
    assert (await api.get(f"/v1/notebooks/{notebook.id}")).json()["title"] == "Biology"


# - - - Delete - - -


async def test_delete_answers_204_without_a_body_and_hides_the_notebook(
    api: AsyncClient, uow_factory: UowFactory, student: Actor
) -> None:
    """NB-3, NB-15: `204`, then the notebook is gone from the list and the page."""
    notebook = await make_notebook(uow_factory, student.user_id)

    deleted = await api.delete(f"/v1/notebooks/{notebook.id}")
    opened = await api.get(f"/v1/notebooks/{notebook.id}")
    listed = (await api.get("/v1/notebooks")).json()

    assert deleted.status_code == 204 and deleted.content == b""
    assert opened.status_code == 404 and problem_type(opened) == "notebooks/not-found"
    assert listed["items"] == []


# - - - Another student's notebook, missing notebook, wrong role - - -


async def test_another_students_notebook_is_a_404_everywhere(
    api: AsyncClient, uow_factory: UowFactory, other_student: Actor
) -> None:
    """NB-15: reading, editing and deleting it looks like a missing notebook."""
    theirs = await make_notebook(uow_factory, other_student.user_id)
    url = f"/v1/notebooks/{theirs.id}"

    responses = [
        await api.get(url),
        await api.patch(url, json={"title": "Mine now"}),
        await api.delete(url),
        await api.get(f"/v1/notebooks/{new_id()}"),
    ]

    assert [r.status_code for r in responses] == [404, 404, 404, 404]
    assert {problem_type(r) for r in responses} == {"notebooks/not-found"}
    again = await api.get("/v1/notebooks")
    assert again.json()["items"] == []


async def test_a_notebook_id_that_is_not_a_uuid_is_a_422(api: AsyncClient) -> None:
    """NB-3: the path parameter is validated."""
    response = await api.get("/v1/notebooks/not-a-uuid")

    assert response.status_code == 422
    assert problem_type(response) == "common/request-validation"


@pytest.mark.parametrize("role", [Role.TEACHER, Role.ADMIN])
async def test_only_students_may_use_notebooks(
    api: AsyncClient,
    current: dict[str, Actor],
    make_actor: Callable[..., Actor],
    uow_factory: UowFactory,
    student: Actor,
    role: Role,
) -> None:
    """NB-1, LMS-AI 3.1: admins get `403` on the student routes (teachers own
    notebooks too) and `404` on a
    student's notebook (the routes of one notebook are open to course staff, whose
    access is checked per notebook)."""
    notebook = await make_notebook(uow_factory, student.user_id)
    current["actor"] = make_actor(role)
    url = f"/v1/notebooks/{notebook.id}"

    student_only = [
        await api.get("/v1/notebooks"),
        await api.post("/v1/notebooks", json={}),
        await api.get("/v1/notebooks/usage"),
    ]
    one_notebook = [
        await api.get(url),
        await api.patch(url, json={"pinned": True}),
        await api.delete(url),
        await api.get(f"{url}/usage"),
    ]

    if role is Role.TEACHER:  # teachers own notebooks too
        assert [r.status_code for r in student_only] == [200, 201, 200]
    else:
        assert [r.status_code for r in student_only] == [403] * 3
        assert {problem_type(r) for r in student_only} == {"common/forbidden"}
    assert [r.status_code for r in one_notebook] == [404] * 4
    assert {problem_type(r) for r in one_notebook} == {"notebooks/not-found"}


# - - - Usage - - -


async def test_usage_is_routed_before_the_notebook_id_and_has_the_contract_keys(
    api: AsyncClient,
) -> None:
    """NB-14: `/notebooks/usage` is not read as an id; the four counters; no audio."""
    response = await api.get("/v1/notebooks/usage")

    body = response.json()
    assert response.status_code == 200, response.text
    assert set(body) == {"budget", "quotas", "generating", "generating_limit"}
    assert set(body["budget"]) == {"session", "day"}
    assert set(body["budget"]["session"]) == USAGE_PART_KEYS
    assert set(body["budget"]["day"]) == USAGE_PART_KEYS
    assert set(body["quotas"]) == {
        "artifacts",
        "audio_overview",
        "slides",
        "infographic",
    }
    assert all(set(q) == USAGE_PART_KEYS for q in body["quotas"].values())
    assert body["quotas"]["audio_overview"]["limit"] == 0
    assert body["quotas"]["artifacts"]["used"] == 0
    assert body["quotas"]["artifacts"]["limit"] > 0
    assert body["generating"] == 0 and body["generating_limit"] > 0
    assert body["budget"]["day"]["used"] == 0 and body["budget"]["day"]["limit"] > 0


# - - - The feature switch - - -


async def test_everything_is_a_404_feature_disabled_when_notebooks_are_off(
    http_client: Any,
    services: NotebooksServices,
    settings: Settings,
    student: Actor,
    uow_factory: UowFactory,
) -> None:
    """NB-1, § 4.7: with the switch off every route is `404 feature-disabled`."""
    notebook = await make_notebook(uow_factory, student.user_id)
    off = settings.model_copy(
        update={"notebooks": settings.notebooks.model_copy(update={"enabled": False})}
    )
    client: AsyncClient = await http_client(
        ROUTERS, {get_actor: lambda: student}, notebooks=services, settings=off
    )
    url = f"/v1/notebooks/{notebook.id}"

    responses = [
        await client.get("/v1/notebooks"),
        await client.post("/v1/notebooks", json={}),
        await client.get("/v1/notebooks/usage"),
        await client.get(url),
        await client.get(f"{url}/sources"),
    ]

    assert [r.status_code for r in responses] == [404] * 5
    assert {problem_type(r) for r in responses} == {"notebooks/feature-disabled"}
