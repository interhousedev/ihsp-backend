"""HTTP: /v1/notebooks/{id}/artifacts* follows the API contract (§ 4.3 to 4.7)."""

import json
from collections.abc import Callable
from datetime import timedelta
from typing import Any
from uuid import UUID

from app.interfaces.http.v1.notebooks.router_studio import router
from app.modules.notebooks.domain.entities import ArtifactError, Notebook, Source
from app.modules.notebooks.domain.enums import ArtifactKind, ArtifactStatus
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.modules.notebooks.wiring import NotebooksServices
from app.settings import Settings
from app.shared.actor import Actor, Role
from tests.factories.notebooks import NOW, make_artifact, make_notebook, make_source
from tests.fakes.clock import FixedClock
from tests.fakes.notebooks.world import World
from tests.fakes.tasks import FakeTaskKicker
from tests.notebooks.unit.studio.helpers import SOURCE_TEXTS

import pytest
from fastapi import FastAPI
from httpx import AsyncClient, Response

ITEM_KEYS = {
    "id",
    "notebook_id",
    "kind",
    "format",
    "title",
    "status",
    "error",
    "options",
    "prompt",
    "source_count",
    "sampled",
    "unread",
    "progress",
    "has_assets",
    "parent_id",
    "flashcard_set_id",
    "created_at",
    "finished_at",
    "suggest_web_search",
}
DETAIL_KEYS = ITEM_KEYS | {
    "content",
    "refs_index",
    "source_map",
    "progress_state",
    "assets",
}
SOURCE_KEYS = {
    "id",
    "notebook_id",
    "kind",
    "title",
    "status",
    "failure",
    "selected",
    "position",
    "word_count",
    "passage_count",
    "origin",
    "ref",
    "stale",
    "has_guide",
    "label_ids",
    "modality",
    "ai_unsupported",
    "synced",
    "synced_at",
    "created_at",
}
GENERATE = "notebooks.generate_artifact"

REPORT = {"kind": "report", "options": {"format": "conspect"}}
CREATE_BODIES: dict[str, dict[str, Any]] = {
    "report": REPORT,
    "mind_map": {"kind": "mind_map"},
    "flashcards": {
        "kind": "flashcards",
        "options": {"count": "fewer", "difficulty": "hard"},
        "prompt": "Only the Calvin cycle",
    },
    "quiz": {"kind": "quiz", "options": {"types": ["single", "multiple"]}},
    "data_table": {"kind": "data_table", "options": {"max_rows": 12}},
    "slides": {"kind": "slides", "options": {"format": "detailed", "length": "short"}},
    "infographic": {"kind": "infographic", "options": {"style": "bento"}},
    "exercise": {
        "kind": "exercise",
        "options": {"exam": "ielts_academic", "skill": "reading", "count": 6},
    },
}


@pytest.fixture
async def notebook(uow_factory: UowFactory, student: Actor) -> Notebook:
    """A notebook of the student."""
    return await make_notebook(uow_factory, student.user_id, title="Biology")


@pytest.fixture
async def source(uow_factory: UowFactory, notebook: Notebook) -> Source:
    """A ready, selected source with four passages."""
    return await make_source(
        uow_factory, notebook, title="Biology 10", texts=SOURCE_TEXTS
    )


def base(notebook: Notebook) -> str:
    """The studio path of a notebook."""
    return f"/v1/notebooks/{notebook.id}/artifacts"


async def create(
    api: AsyncClient, notebook: Notebook, body: dict[str, Any]
) -> dict[str, Any]:
    """POST an output request and return the queued item."""
    response = await api.post(base(notebook), json=body)
    assert response.status_code == 202, response.text
    item: dict[str, Any] = response.json()
    return item


async def generated(
    api: AsyncClient,
    services: NotebooksServices,
    notebook: Notebook,
    body: dict[str, Any],
) -> dict[str, Any]:
    """Request an output and run its job; return the item that was queued."""
    item = await create(api, notebook, body)
    await services.generate_artifact.execute(UUID(item["id"]))
    return item


async def detail(
    api: AsyncClient, notebook: Notebook, item: dict[str, Any]
) -> dict[str, Any]:
    """GET the detail of an output."""
    response = await api.get(f"{base(notebook)}/{item['id']}")
    assert response.status_code == 200, response.text
    opened: dict[str, Any] = response.json()
    return opened


def problem_type(response: Response) -> str:
    """The `type` of an `application/problem+json` answer."""
    assert response.headers["content-type"].startswith("application/problem+json")
    return str(response.json()["type"])


# - - - Create - - -


@pytest.mark.parametrize("kind", list(CREATE_BODIES))
async def test_creating_an_output_answers_202_with_the_queued_item(
    api: AsyncClient,
    notebook: Notebook,
    source: Source,
    kicker: FakeTaskKicker,
    kind: str,
) -> None:
    """NB-8, NB-9: every kind is queued at once; the job is started."""
    body = CREATE_BODIES[kind]

    response = await api.post(base(notebook), json=body)

    item = response.json()
    assert response.status_code == 202, response.text
    assert set(item) == ITEM_KEYS
    assert item["kind"] == kind
    assert item["status"] == "queued"
    assert item["notebook_id"] == str(notebook.id)
    assert item["source_count"] == 1
    assert item["prompt"] == body.get("prompt")
    assert item["error"] is None and item["finished_at"] is None
    assert item["unread"] is False and item["has_assets"] is False
    assert item["parent_id"] is None and item["flashcard_set_id"] is None
    for key, value in body.get("options", {}).items():
        assert item["options"][key] == value
    assert (GENERATE, {"artifact_id": item["id"]}) in kicker.calls


async def test_options_are_echoed_back_with_the_defaults_filled(
    api: AsyncClient, notebook: Notebook, source: Source
) -> None:
    """NB-9: "View prompt" shows what was used, including the server's defaults."""
    quiz = await create(api, notebook, {"kind": "quiz"})
    report = await create(api, notebook, REPORT)

    assert quiz["options"] == {
        "count": "standard",
        "difficulty": "medium",
        "types": ["single", "multiple", "true_false"],
        "target_count": 10,
        "mode": "auto",
    }
    assert report["format"] == "conspect"
    assert report["options"]["detail"] == "standard"
    assert report["options"]["style"] == "outline"


async def test_the_sources_of_a_request_can_be_named(
    api: AsyncClient, notebook: Notebook, source: Source, uow_factory: UowFactory
) -> None:
    """NB-8: `options.source_ids` picks a subset of the ready sources."""
    other = await make_source(uow_factory, notebook, title="Chemistry", texts=("x",))
    body = {"kind": "mind_map", "options": {"source_ids": [str(other.id)]}}

    item = await create(api, notebook, body)

    assert item["source_count"] == 1
    assert item["options"]["source_ids"] == [str(other.id)]


@pytest.mark.parametrize(
    "body",
    [
        {"kind": "audio_overview"},
        {"kind": "audio_overview", "options": {"format": "brief"}},
        {"kind": "video_overview"},
        {},
        {"kind": "report"},
        {"kind": "report", "options": {}},
        {"kind": "quiz", "options": {"count": "huge"}},
        {"kind": "data_table", "options": {"max_rows": 500}},
    ],
    ids=[
        "audio",
        "audio-with-options",
        "unknown-kind",
        "no-kind",
        "report-without-options",
        "report-without-format",
        "bad-enum",
        "bad-range",
    ],
)
async def test_a_request_that_does_not_match_the_contract_is_a_422(
    api: AsyncClient,
    notebook: Notebook,
    source: Source,
    kicker: FakeTaskKicker,
    body: dict[str, Any],
) -> None:
    """NB-8: audio is not a kind; the others fail validation; nothing is queued."""
    response = await api.post(base(notebook), json=body)

    assert response.status_code == 422
    assert problem_type(response) == "common/request-validation"
    assert kicker.calls == []
    assert (await api.get(base(notebook))).json() == []


async def test_a_custom_report_needs_the_focus_text(
    api: AsyncClient, notebook: Notebook, source: Source, kicker: FakeTaskKicker
) -> None:
    """NB-8: the use case rejects what validation cannot see (422 invalid-options)."""
    custom = {"kind": "report", "options": {"format": "custom"}}

    refused = await api.post(base(notebook), json=custom)
    accepted = await api.post(base(notebook), json={**custom, "prompt": "A poem"})

    assert refused.status_code == 422
    assert problem_type(refused) == "notebooks/invalid-options"
    assert accepted.status_code == 202
    assert accepted.json()["prompt"] == "A poem"
    assert len(kicker.calls) == 1


async def test_the_openapi_document_has_no_audio_or_video() -> None:
    """NB-8: no audio kind, no assets, no audio.wav, no discover."""
    app = FastAPI()
    app.include_router(router)

    paths = set(app.openapi()["paths"])
    assert len(paths) == 18  # with Apply, attach-to-lesson, plans, exercise feedback
    assert not [p for p in paths if "assets" in p or "audio" in p or "discover" in p]
    # (the step-draft schemas of the Apply routes legitimately name a video block)
    assert '"audio"' not in json.dumps(app.openapi()["paths"])


# - - - Errors on create - - -


async def test_a_notebook_without_sources_still_queues_an_output(
    api: AsyncClient, notebook: Notebook, kicker: FakeTaskKicker
) -> None:
    """T6.3: nothing selected is allowed; the output is made without sources."""
    response = await api.post(base(notebook), json={"kind": "mind_map"})

    assert response.status_code == 202
    assert kicker.calls != []


async def test_the_daily_count_of_outputs_is_a_429_with_the_limit(
    api: AsyncClient,
    notebook: Notebook,
    source: Source,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """NB-14: past the daily limit the answer is 429 notebooks/quota-exceeded."""
    monkeypatch.setattr(settings.limits, "nb_artifacts_per_day", 1)
    await create(api, notebook, {"kind": "mind_map"})

    response = await api.post(base(notebook), json={"kind": "mind_map"})

    assert response.status_code == 429
    assert problem_type(response) == "notebooks/quota-exceeded"
    params = response.json()["params"]
    assert (params["kind"], params["limit"]) == ("artifacts", 1)
    assert "resets_at" in params


async def test_a_fourth_output_at_once_is_a_409_busy(
    api: AsyncClient, notebook: Notebook, source: Source
) -> None:
    """NB-14: at most three outputs are queued or generating."""
    for _ in range(3):
        await create(api, notebook, {"kind": "mind_map"})

    response = await api.post(base(notebook), json={"kind": "mind_map"})

    assert response.status_code == 409
    assert problem_type(response) == "notebooks/busy"
    assert len((await api.get(base(notebook))).json()) == 3


# - - - List - - -


async def test_the_list_filters_by_kind_and_status_newest_first(
    api: AsyncClient, notebook: Notebook, uow_factory: UowFactory
) -> None:
    """NB-9: `?kind` and `?status`; items have no content; deleted ones are gone."""
    report = await make_artifact(uow_factory, notebook, created_at=NOW)
    quiz = await make_artifact(
        uow_factory, notebook, ArtifactKind.QUIZ, created_at=NOW + timedelta(hours=1)
    )
    failed_quiz = await make_artifact(
        uow_factory,
        notebook,
        ArtifactKind.QUIZ,
        ArtifactStatus.FAILED,
        created_at=NOW + timedelta(hours=2),
    )
    slides = await make_artifact(
        uow_factory,
        notebook,
        ArtifactKind.SLIDES,
        ArtifactStatus.QUEUED,
        created_at=NOW + timedelta(hours=3),
    )
    await make_artifact(
        uow_factory, notebook, ArtifactKind.QUIZ, deleted_at=NOW + timedelta(hours=4)
    )

    async def ids(**params: str) -> list[str]:
        response = await api.get(base(notebook), params=params)
        assert response.status_code == 200, response.text
        items = response.json()
        assert all(set(item) == ITEM_KEYS for item in items)
        return [item["id"] for item in items]

    assert await ids() == [str(a.id) for a in (slides, failed_quiz, quiz, report)]
    assert await ids(kind="quiz") == [str(failed_quiz.id), str(quiz.id)]
    assert await ids(status="ready") == [str(quiz.id), str(report.id)]
    assert await ids(kind="quiz", status="ready") == [str(quiz.id)]
    assert await ids(kind="mind_map") == []


@pytest.mark.parametrize("params", [{"kind": "audio_overview"}, {"status": "done"}])
async def test_the_list_refuses_filters_that_are_not_in_the_contract(
    api: AsyncClient, notebook: Notebook, params: dict[str, str]
) -> None:
    """NB-8: the audio kind is not a filter value either."""
    response = await api.get(base(notebook), params=params)

    assert response.status_code == 422
    assert problem_type(response) == "common/request-validation"


async def test_a_failed_output_carries_its_error_code_and_message_key(
    api: AsyncClient, notebook: Notebook, uow_factory: UowFactory
) -> None:
    """NB-9: the web translates `message_key`; the list shows what went wrong."""
    error = ArtifactError(
        code="provider_error", message_key="notebooks-provider-error", params={"n": 2}
    )
    failed = await make_artifact(
        uow_factory, notebook, ArtifactKind.QUIZ, ArtifactStatus.FAILED, error=error
    )

    items = (await api.get(base(notebook))).json()

    assert [item["id"] for item in items] == [str(failed.id)]
    assert items[0]["error"] == {
        "code": "provider_error",
        "message_key": "notebooks-provider-error",
        "params": {"n": 2},
    }
    assert items[0]["unread"] is False


# - - - Detail - - -


@pytest.mark.parametrize("kind", list(CREATE_BODIES))
async def test_a_generated_output_opens_with_content_and_references(
    api: AsyncClient,
    services: NotebooksServices,
    notebook: Notebook,
    source: Source,
    kind: str,
) -> None:
    """NB-8, NB-20: content, refs_index and the source map come with the detail."""
    item = await generated(api, services, notebook, CREATE_BODIES[kind])

    opened = await detail(api, notebook, item)

    assert set(opened) == DETAIL_KEYS
    assert opened["status"] == "ready" and opened["error"] is None
    assert opened["kind"] == kind
    assert opened["title"] and opened["content"]["title"]
    assert opened["source_map"] == {"S1": str(source.id)}
    assert opened["progress_state"] is None
    assert opened["assets"] == [] and opened["has_assets"] is False
    assert opened["finished_at"] is not None
    if kind == "report":
        assert opened["refs_index"] == {}
        assert opened["content"]["citations"]
    else:
        assert opened["refs_index"]
        entry = next(iter(opened["refs_index"].values()))
        assert set(entry) == {
            "passage_id",
            "source_id",
            "source_title",
            "source_kind",
            "page",
            "snippet",
        }
        assert entry["source_id"] == str(source.id)


async def test_the_first_view_clears_the_blue_dot_and_later_views_keep_the_time(
    api: AsyncClient,
    services: NotebooksServices,
    notebook: Notebook,
    source: Source,
    uow_factory: UowFactory,
    clock: FixedClock,
) -> None:
    """NB-9: `unread` until the first GET of the detail; `viewed_at` is set once."""
    item = await generated(api, services, notebook, {"kind": "mind_map"})
    listed = (await api.get(base(notebook))).json()
    assert [(i["id"], i["unread"]) for i in listed] == [(item["id"], True)]

    first = await detail(api, notebook, item)
    clock.advance(hours=1)
    second = await detail(api, notebook, item)

    assert first["unread"] is False and second["unread"] is False
    assert (await api.get(base(notebook))).json()[0]["unread"] is False
    async with uow_factory() as uow:
        stored = await uow.artifacts.get(UUID(item["id"]))
    assert stored is not None
    assert stored.viewed_at == clock.now() - timedelta(hours=1)


async def test_an_output_that_is_not_ready_opens_without_content(
    api: AsyncClient, notebook: Notebook, source: Source
) -> None:
    """NB-9: a queued output has no content; opening it does not clear anything."""
    item = await create(api, notebook, {"kind": "quiz"})

    opened = await detail(api, notebook, item)

    assert opened["status"] == "queued"
    assert opened["content"] is None and opened["refs_index"] == {}


# - - - Rename, delete, cancel, retry - - -


async def test_an_output_can_be_renamed(
    api: AsyncClient, notebook: Notebook, source: Source
) -> None:
    """NB-9: PATCH changes the title and answers the item."""
    item = await create(api, notebook, {"kind": "quiz"})

    response = await api.patch(
        f"{base(notebook)}/{item['id']}", json={"title": "  Cell   quiz "}
    )

    assert response.status_code == 200
    assert set(response.json()) == ITEM_KEYS
    assert response.json()["title"] == "Cell quiz"
    assert (await detail(api, notebook, item))["title"] == "Cell quiz"


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ({"title": "   "}, "notebooks/invalid-options"),
        ({}, "common/request-validation"),
    ],
)
async def test_a_bad_title_is_a_422(
    api: AsyncClient,
    notebook: Notebook,
    source: Source,
    body: dict[str, Any],
    expected: str,
) -> None:
    """NB-9: an empty title is refused and the old one stays."""
    item = await create(api, notebook, {"kind": "quiz"})

    response = await api.patch(f"{base(notebook)}/{item['id']}", json=body)

    assert response.status_code == 422
    assert problem_type(response) == expected
    assert (await detail(api, notebook, item))["title"] == item["title"]


async def test_a_deleted_output_is_gone(
    api: AsyncClient, notebook: Notebook, source: Source
) -> None:
    """NB-9: DELETE answers 204 and the output disappears from list and detail."""
    item = await create(api, notebook, {"kind": "quiz"})

    response = await api.delete(f"{base(notebook)}/{item['id']}")

    assert response.status_code == 204 and response.content == b""
    assert (await api.get(base(notebook))).json() == []
    missing = await api.get(f"{base(notebook)}/{item['id']}")
    assert missing.status_code == 404
    assert problem_type(missing) == "notebooks/not-found"


async def test_a_queued_output_can_be_canceled_and_retried(
    api: AsyncClient,
    notebook: Notebook,
    source: Source,
    kicker: FakeTaskKicker,
) -> None:
    """NB-9: cancel answers the item; retry answers 202 and starts the job again."""
    item = await create(api, notebook, {"kind": "quiz"})
    url = f"{base(notebook)}/{item['id']}"

    canceled = await api.post(f"{url}/cancel")
    again = await api.post(f"{url}/cancel")
    retried = await api.post(f"{url}/retry")

    assert canceled.status_code == 200
    assert set(canceled.json()) == ITEM_KEYS
    assert canceled.json()["status"] == "canceled"
    assert again.status_code == 409
    assert problem_type(again) == "notebooks/artifact-not-ready"
    assert retried.status_code == 202
    assert set(retried.json()) == ITEM_KEYS
    assert retried.json()["status"] == "queued"
    assert retried.json()["id"] == item["id"]
    assert kicker.calls.count((GENERATE, {"artifact_id": item["id"]})) == 2


async def test_a_failed_output_can_be_retried_but_a_ready_one_cannot(
    api: AsyncClient, notebook: Notebook, source: Source, uow_factory: UowFactory
) -> None:
    """NB-9: only failed and canceled outputs are queued again."""
    failed = await make_artifact(
        uow_factory, notebook, ArtifactKind.QUIZ, ArtifactStatus.FAILED
    )
    ready = await make_artifact(uow_factory, notebook, ArtifactKind.QUIZ)

    retried = await api.post(f"{base(notebook)}/{failed.id}/retry")
    refused = await api.post(f"{base(notebook)}/{ready.id}/retry")
    not_running = await api.post(f"{base(notebook)}/{ready.id}/cancel")

    assert retried.status_code == 202 and retried.json()["status"] == "queued"
    assert refused.status_code == 409 and not_running.status_code == 409
    assert problem_type(refused) == "notebooks/artifact-not-ready"


# - - - Progress - - -


@pytest.mark.parametrize("kind", ["flashcards", "quiz"])
async def test_progress_is_saved_and_comes_back_with_the_detail(
    api: AsyncClient,
    services: NotebooksServices,
    notebook: Notebook,
    source: Source,
    kind: str,
) -> None:
    """NB-10, NB-11: PUT answers 204; the detail returns the latest state."""
    item = await generated(api, services, notebook, CREATE_BODIES[kind])
    url = f"{base(notebook)}/{item['id']}/progress"

    first = await api.put(url, json={"state": {"known": ["c1"], "position": 1}})
    second = await api.put(url, json={"state": {"known": ["c1", "c2"], "current": 2}})

    assert first.status_code == 204 and first.content == b""
    assert second.status_code == 204
    opened = await detail(api, notebook, item)
    assert opened["progress_state"] == {"known": ["c1", "c2"], "current": 2}


async def test_progress_over_16_kb_is_a_422_and_the_old_state_stays(
    api: AsyncClient,
    services: NotebooksServices,
    notebook: Notebook,
    source: Source,
) -> None:
    """NB-10: an oversize state is a 4xx problem, never a 500."""
    item = await generated(api, services, notebook, CREATE_BODIES["quiz"])
    url = f"{base(notebook)}/{item['id']}/progress"
    await api.put(url, json={"state": {"answers": "a" * 16_000}})

    response = await api.put(url, json={"state": {"answers": "a" * 17_000}})

    assert response.status_code == 422
    assert problem_type(response) == "notebooks/invalid-options"
    opened = await detail(api, notebook, item)
    assert opened["progress_state"] == {"answers": "a" * 16_000}


@pytest.mark.parametrize(
    ("body", "expected"),
    [({}, "common/request-validation"), ({"state": [1]}, "common/request-validation")],
)
async def test_progress_state_must_be_an_object(
    api: AsyncClient,
    notebook: Notebook,
    uow_factory: UowFactory,
    body: dict[str, Any],
    expected: str,
) -> None:
    """NB-10: `{state: object}` is required."""
    quiz = await make_artifact(uow_factory, notebook, ArtifactKind.QUIZ)

    response = await api.put(f"{base(notebook)}/{quiz.id}/progress", json=body)

    assert response.status_code == 422
    assert problem_type(response) == expected


async def test_progress_needs_a_ready_deck_or_quiz(
    api: AsyncClient, notebook: Notebook, source: Source, uow_factory: UowFactory
) -> None:
    """NB-10: other kinds answer 422, an unfinished output 409."""
    report = await make_artifact(uow_factory, notebook, ArtifactKind.REPORT)
    queued = await create(api, notebook, {"kind": "quiz"})

    on_report = await api.put(
        f"{base(notebook)}/{report.id}/progress", json={"state": {}}
    )
    on_queued = await api.put(
        f"{base(notebook)}/{queued['id']}/progress", json={"state": {}}
    )

    assert on_report.status_code == 422
    assert problem_type(on_report) == "notebooks/invalid-options"
    assert on_queued.status_code == 409
    assert problem_type(on_queued) == "notebooks/artifact-not-ready"


# - - - Add as source and flash card set - - -


async def test_a_report_is_added_to_the_sources_as_a_note(
    api: AsyncClient,
    services: NotebooksServices,
    notebook: Notebook,
    source: Source,
    kicker: FakeTaskKicker,
) -> None:
    """NB-13: POST save-as-source answers 201 with the new note source."""
    item = await generated(api, services, notebook, REPORT)

    response = await api.post(f"{base(notebook)}/{item['id']}/save-as-source")

    note = response.json()
    assert response.status_code == 201, response.text
    assert set(note) == SOURCE_KEYS
    assert (note["kind"], note["status"]) == ("note", "pending")
    assert note["notebook_id"] == str(notebook.id)
    assert ("notebooks.process_source", {"source_id": note["id"]}) in kicker.calls
    sources = (await api.get(f"/v1/notebooks/{notebook.id}/sources")).json()
    assert note["id"] in [s["id"] for s in sources]


async def test_only_a_ready_report_can_be_added_as_a_source(
    api: AsyncClient, notebook: Notebook, source: Source, uow_factory: UowFactory
) -> None:
    """NB-13: other kinds answer 422, an unfinished report 409."""
    quiz = await make_artifact(uow_factory, notebook, ArtifactKind.QUIZ)
    queued = await create(api, notebook, REPORT)

    on_quiz = await api.post(f"{base(notebook)}/{quiz.id}/save-as-source")
    on_queued = await api.post(f"{base(notebook)}/{queued['id']}/save-as-source")

    assert on_quiz.status_code == 422
    assert problem_type(on_quiz) == "notebooks/invalid-options"
    assert on_queued.status_code == 409
    assert problem_type(on_queued) == "notebooks/artifact-not-ready"


async def test_a_deck_becomes_one_flash_card_set_however_often_it_is_asked(
    api: AsyncClient,
    services: NotebooksServices,
    notebook: Notebook,
    source: Source,
    world: World,
) -> None:
    """NB-10: `created` is true once, then false with the same set id."""
    item = await generated(api, services, notebook, CREATE_BODIES["flashcards"])
    url = f"{base(notebook)}/{item['id']}/flashcard-set"

    first = await api.post(url)
    second = await api.post(url)

    assert first.status_code == 200 and second.status_code == 200
    assert set(first.json()) == {"set_id", "created"}
    assert first.json()["created"] is True
    assert second.json() == {"set_id": first.json()["set_id"], "created": False}
    assert len(world.flashcards.create_calls) == 1
    opened = await detail(api, notebook, item)
    assert opened["flashcard_set_id"] == first.json()["set_id"]


async def test_only_a_ready_deck_can_be_saved_as_a_set(
    api: AsyncClient, notebook: Notebook, source: Source, uow_factory: UowFactory
) -> None:
    """NB-10: other kinds answer 422, an unfinished deck 409."""
    quiz = await make_artifact(uow_factory, notebook, ArtifactKind.QUIZ)
    queued = await create(api, notebook, CREATE_BODIES["flashcards"])

    on_quiz = await api.post(f"{base(notebook)}/{quiz.id}/flashcard-set")
    on_queued = await api.post(f"{base(notebook)}/{queued['id']}/flashcard-set")

    assert on_quiz.status_code == 422
    assert on_queued.status_code == 409


# - - - Slides - - -


@pytest.fixture
async def deck(
    api: AsyncClient, services: NotebooksServices, notebook: Notebook, source: Source
) -> dict[str, Any]:
    """A generated slide deck, opened (detail)."""
    item = await generated(api, services, notebook, CREATE_BODIES["slides"])
    return await detail(api, notebook, item)


async def test_edited_slides_are_saved_and_answered_as_the_detail(
    api: AsyncClient, notebook: Notebook, deck: dict[str, Any]
) -> None:
    """NB-8: PUT slides replaces titles, order and deleted slides."""
    slides = deck["content"]["slides"]
    slides[1]["title"] = "Two stages of photosynthesis"
    del slides[4]
    slides[2], slides[3] = slides[3], slides[2]

    response = await api.put(
        f"{base(notebook)}/{deck['id']}/slides", json={"slides": slides}
    )

    saved = response.json()
    assert response.status_code == 200, response.text
    assert set(saved) == DETAIL_KEYS
    assert [s["id"] for s in saved["content"]["slides"]] == [s["id"] for s in slides]
    assert saved["content"]["slides"][1]["title"] == "Two stages of photosynthesis"
    assert saved["content"]["title"] == deck["content"]["title"]
    assert saved["refs_index"] == deck["refs_index"]
    assert (await detail(api, notebook, deck))["content"] == saved["content"]


@pytest.mark.parametrize("slides", [[], [{"id": "s1"}]], ids=["none", "no-layout"])
async def test_unusable_slides_are_a_422_and_change_nothing(
    api: AsyncClient, notebook: Notebook, deck: dict[str, Any], slides: list[Any]
) -> None:
    """NB-20: edits are validated like generated slides."""
    response = await api.put(
        f"{base(notebook)}/{deck['id']}/slides", json={"slides": slides}
    )

    assert response.status_code == 422
    assert problem_type(response) == "notebooks/invalid-options"
    assert (await detail(api, notebook, deck))["content"] == deck["content"]


async def test_only_a_ready_deck_has_slides_to_edit(
    api: AsyncClient, notebook: Notebook, source: Source, uow_factory: UowFactory
) -> None:
    """NB-8: other kinds answer 422, an unfinished deck 409."""
    quiz = await make_artifact(uow_factory, notebook, ArtifactKind.QUIZ)
    queued = await create(api, notebook, CREATE_BODIES["slides"])

    on_quiz = await api.put(f"{base(notebook)}/{quiz.id}/slides", json={"slides": []})
    on_queued = await api.put(
        f"{base(notebook)}/{queued['id']}/slides", json={"slides": []}
    )

    assert on_quiz.status_code == 422
    assert on_queued.status_code == 409


async def test_a_revision_is_a_new_queued_deck_that_points_to_its_parent(
    api: AsyncClient,
    services: NotebooksServices,
    notebook: Notebook,
    deck: dict[str, Any],
    kicker: FakeTaskKicker,
) -> None:
    """NB-8: revise answers 202 with a new output (`parent_id`); its job finishes."""
    changes = [{"slide_id": "s2", "instruction": "Make it shorter"}]

    response = await api.post(
        f"{base(notebook)}/{deck['id']}/slides/revise", json={"changes": changes}
    )

    revision = response.json()
    assert response.status_code == 202, response.text
    assert set(revision) == ITEM_KEYS
    assert revision["id"] != deck["id"]
    assert (revision["kind"], revision["status"]) == ("slides", "queued")
    assert revision["parent_id"] == deck["id"]
    assert (GENERATE, {"artifact_id": revision["id"]}) in kicker.calls
    await services.generate_artifact.execute(UUID(revision["id"]))
    opened = await detail(api, notebook, revision)
    assert opened["status"] == "ready"
    assert opened["parent_id"] == deck["id"]
    assert opened["content"]["slides"]
    assert len((await api.get(base(notebook))).json()) == 2


@pytest.mark.parametrize(
    "changes",
    [
        [],
        [{"slide_id": "nope", "instruction": "Shorter"}],
        [{"slide_id": "s2", "instruction": "  "}],
        [
            {"slide_id": "s2", "instruction": "Shorter"},
            {"slide_id": "s2", "instruction": "Longer"},
        ],
    ],
    ids=["none", "unknown-slide", "blank-instruction", "slide-twice"],
)
async def test_a_bad_revision_is_a_422_and_creates_nothing(
    api: AsyncClient,
    notebook: Notebook,
    deck: dict[str, Any],
    changes: list[dict[str, str]],
) -> None:
    """NB-8: the changes are checked against the deck."""
    response = await api.post(
        f"{base(notebook)}/{deck['id']}/slides/revise", json={"changes": changes}
    )

    assert response.status_code == 422
    assert problem_type(response) == "notebooks/invalid-options"
    assert len((await api.get(base(notebook))).json()) == 1


# - - - Access - - -


@pytest.mark.parametrize(
    ("method", "suffix", "body"),
    [
        ("GET", "", None),
        ("PATCH", "", {"title": "Mine now"}),
        ("DELETE", "", None),
        ("POST", "/cancel", None),
        ("POST", "/retry", None),
        ("PUT", "/progress", {"state": {}}),
        ("POST", "/save-as-source", None),
        ("POST", "/flashcard-set", None),
        ("PUT", "/slides", {"slides": []}),
        ("POST", "/slides/revise", {"changes": []}),
    ],
)
async def test_another_students_output_answers_404(
    api: AsyncClient,
    uow_factory: UowFactory,
    other_student: Actor,
    method: str,
    suffix: str,
    body: dict[str, Any] | None,
) -> None:
    """NB-8: a notebook or output of someone else is `notebooks/not-found`."""
    theirs = await make_notebook(uow_factory, other_student.user_id)
    output = await make_artifact(uow_factory, theirs, ArtifactKind.QUIZ)

    response = await api.request(
        method, f"{base(theirs)}/{output.id}{suffix}", json=body
    )

    assert response.status_code == 404
    assert problem_type(response) == "notebooks/not-found"


async def test_another_students_notebook_has_no_studio_for_me(
    api: AsyncClient, uow_factory: UowFactory, other_student: Actor
) -> None:
    """NB-8: list and create on someone else's notebook answer 404."""
    theirs = await make_notebook(uow_factory, other_student.user_id)
    await make_source(uow_factory, theirs, texts=SOURCE_TEXTS)

    listed = await api.get(base(theirs))
    created = await api.post(base(theirs), json={"kind": "mind_map"})

    assert (listed.status_code, created.status_code) == (404, 404)
    assert problem_type(created) == "notebooks/not-found"


async def test_an_output_is_found_only_through_its_own_notebook(
    api: AsyncClient, notebook: Notebook, uow_factory: UowFactory, student: Actor
) -> None:
    """NB-8: the id of an output of another notebook does not open it."""
    elsewhere = await make_notebook(uow_factory, student.user_id, title="Chemistry")
    output = await make_artifact(uow_factory, elsewhere, ArtifactKind.QUIZ)

    response = await api.get(f"{base(notebook)}/{output.id}")

    assert response.status_code == 404
    assert (await api.get(f"{base(elsewhere)}/{output.id}")).status_code == 200


@pytest.mark.parametrize("role", [Role.TEACHER, Role.ADMIN])
async def test_staff_cannot_use_the_studio(
    api: AsyncClient,
    notebook: Notebook,
    current: dict[str, Actor],
    make_actor: Callable[..., Actor],
    role: Role,
) -> None:
    """NB-8, LMS-AI 3.1: a student's Studio is theirs; staff get the 404 of a
    missing notebook."""
    current["actor"] = make_actor(role)

    listed = await api.get(base(notebook))
    created = await api.post(base(notebook), json={"kind": "mind_map"})

    assert (listed.status_code, created.status_code) == (404, 404)
