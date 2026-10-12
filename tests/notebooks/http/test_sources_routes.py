"""HTTP: sources and passages under /v1/notebooks/{id} follow § 4.3 / § 4.4."""

from collections.abc import Callable
from typing import Any
from uuid import UUID

from app.modules.notebooks.domain.entities import Citation, Notebook, SourceGuide
from app.modules.notebooks.domain.enums import SourceKind, SourceStatus
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.shared.actor import Actor, Role
from app.shared.i18n.core import I18nCore
from app.shared.ids import new_id
from tests.factories.notebooks import make_notebook, make_source
from tests.fakes.ai.contracts import make_file
from tests.fakes.notebooks.world import World
from tests.fakes.tasks import FakeTaskKicker

import pytest
from httpx import AsyncClient, Response

PROCESS_TASK = "notebooks.process_source"
ITEM_KEYS = {
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
    "synced_at",
    "created_at",
    "label_ids",
    "modality",
    "ai_unsupported",
}
DETAIL_KEYS = ITEM_KEYS | {"guide", "body_md", "editable", "citations", "file"}
PASSAGE_KEYS = {"id", "seq", "text", "page", "heading"}
PROBLEM_KEYS = {"type", "title", "status", "message_key", "params"}
TEXTS = tuple(
    f"Passage {n} says that plants make sugar from light." for n in range(1, 6)
)


def problem_type(response: Response) -> str:
    """The `type` of a problem+json response (and check its media type)."""
    assert response.headers["content-type"].startswith("application/problem+json")
    return str(response.json()["type"])


def text_item(n: int = 1) -> dict[str, Any]:
    """A pasted-text item of `POST sources`."""
    return {"kind": "text", "title": f"Text {n}", "text": f"Photosynthesis {n}."}


@pytest.fixture
async def notebook(uow_factory: UowFactory, student: Actor) -> Notebook:
    """An empty notebook of the student."""
    return await make_notebook(uow_factory, student.user_id, title="Biology")


@pytest.fixture
async def theirs(uow_factory: UowFactory, other_student: Actor) -> Notebook:
    """A notebook of the other student."""
    return await make_notebook(uow_factory, other_student.user_id)


def sources_url(notebook: Notebook, suffix: str = "") -> str:
    """`/v1/notebooks/{id}/sources` plus a suffix."""
    return f"/v1/notebooks/{notebook.id}/sources{suffix}"


# - - - Add - - -


async def test_add_stores_every_kind_as_pending_and_starts_the_processing(
    api: AsyncClient,
    world: World,
    student: Actor,
    notebook: Notebook,
    kicker: FakeTaskKicker,
) -> None:
    """NB-2: `201 {items, rejected: []}`, SourceItem keys, one job per source."""
    file = world.files.add_text(make_file(student.user_id), "Text of the file.")
    chat = world.chats.add_chat(student.user_id)
    items = [
        {"kind": "file", "file_id": str(file.id)},
        {"kind": "chat", "chat_id": str(chat.id), "until_seq": 2},
        text_item(),
        {"kind": "note", "title": "My note", "body_md": "# Cells"},
    ]

    response = await api.post(sources_url(notebook), json={"items": items})

    body = response.json()
    assert response.status_code == 201, response.text
    assert set(body) == {"items", "rejected"}
    assert body["rejected"] == []
    assert [set(item) for item in body["items"]] == [ITEM_KEYS] * 4
    assert [item["kind"] for item in body["items"]] == [
        "file",
        "chat",
        "text",
        "note",
    ]
    assert [item["position"] for item in body["items"]] == [1, 2, 3, 4]
    assert {item["status"] for item in body["items"]} == {"pending"}
    assert all(item["selected"] and not item["stale"] for item in body["items"])
    assert all(item["notebook_id"] == str(notebook.id) for item in body["items"])
    assert body["items"][0]["ref"]["file_id"] == str(file.id)
    assert kicker.calls == [
        (PROCESS_TASK, {"source_id": item["id"]}) for item in body["items"]
    ]


async def test_a_refused_item_is_reported_and_the_others_are_stored(
    api: AsyncClient,
    world: World,
    i18n: I18nCore,
    other_student: Actor,
    notebook: Notebook,
    kicker: FakeTaskKicker,
) -> None:
    """NB-2: partial success; `rejected[].error` is shaped like a problem+json body."""
    foreign = world.files.add_text(make_file(other_student.user_id), "Not yours.")
    items = [text_item(1), {"kind": "file", "file_id": str(foreign.id)}, text_item(3)]

    response = await api.post(sources_url(notebook), json={"items": items})

    body = response.json()
    assert response.status_code == 201, response.text
    assert [item["title"] for item in body["items"]] == ["Text 1", "Text 3"]
    assert [item["position"] for item in body["items"]] == [1, 2]
    assert len(body["rejected"]) == 1
    rejected = body["rejected"][0]
    assert set(rejected) == {"index", "error"}
    assert rejected["index"] == 1
    assert set(rejected["error"]) == PROBLEM_KEYS
    assert rejected["error"] == {
        "type": "notebooks/source-forbidden",
        "title": i18n.t("en", "notebooks-source-forbidden"),
        "status": 403,
        "message_key": "notebooks-source-forbidden",
        "params": {},
    }
    assert [kicked[1]["source_id"] for kicked in kicker.calls] == [
        item["id"] for item in body["items"]
    ]


async def test_a_duplicate_is_a_rejected_item_not_a_409_for_the_request(
    api: AsyncClient,
    world: World,
    student: Actor,
    notebook: Notebook,
    kicker: FakeTaskKicker,
) -> None:
    """NB-2, § 4.7: the same file again, or twice in a batch, is `source-duplicate`."""
    file = world.files.add_text(make_file(student.user_id), "Text of the file.")
    chat = world.chats.add_chat(student.user_id)
    item = {"kind": "file", "file_id": str(file.id)}
    first = await api.post(sources_url(notebook), json={"items": [item]})
    kicker.calls.clear()

    again = await api.post(sources_url(notebook), json={"items": [item]})
    batch = await api.post(
        sources_url(notebook),
        json={"items": [{"kind": "chat", "chat_id": str(chat.id)}] * 2},
    )

    assert first.status_code == 201 and len(first.json()["items"]) == 1
    assert again.status_code == 201, again.text
    assert again.json()["items"] == []
    assert [r["index"] for r in again.json()["rejected"]] == [0]
    assert again.json()["rejected"][0]["error"]["type"] == "notebooks/source-duplicate"
    assert again.json()["rejected"][0]["error"]["status"] == 409
    assert batch.status_code == 201
    assert len(batch.json()["items"]) == 1
    assert [r["index"] for r in batch.json()["rejected"]] == [1]
    assert [call[0] for call in kicker.calls] == [PROCESS_TASK]
    assert len((await api.get(sources_url(notebook))).json()) == 2


async def test_when_every_item_is_refused_nothing_is_stored_or_started(
    api: AsyncClient,
    world: World,
    other_student: Actor,
    notebook: Notebook,
    kicker: FakeTaskKicker,
) -> None:
    """NB-2: `201` with no items, one rejection per item, no job."""
    foreign = world.files.add_text(make_file(other_student.user_id), "Not yours.")
    items = [
        {"kind": "file", "file_id": str(foreign.id)},
        {"kind": "chat", "chat_id": str(new_id())},
    ]

    response = await api.post(sources_url(notebook), json={"items": items})

    body = response.json()
    assert response.status_code == 201, response.text
    assert body["items"] == []
    assert [r["index"] for r in body["rejected"]] == [0, 1]
    assert {r["error"]["type"] for r in body["rejected"]} == {
        "notebooks/source-forbidden"
    }
    assert kicker.calls == []
    assert (await api.get(sources_url(notebook))).json() == []


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"items": []},
        {"items": [text_item(n) for n in range(21)]},
        {"items": [{"kind": "video", "url": "https://example.com/v"}]},
        {"items": [{"kind": "text", "text": "No title."}]},
        {"items": [{"kind": "text", "title": "T", "text": ""}]},
        {"items": [{"kind": "file", "file_id": "not-a-uuid"}]},
        {"items": ["text"]},
    ],
)
async def test_add_rejects_a_bad_body_with_422(
    api: AsyncClient, notebook: Notebook, kicker: FakeTaskKicker, body: dict[str, Any]
) -> None:
    """NB-2: 1 to 20 items, each a known `kind` with its fields."""
    response = await api.post(sources_url(notebook), json=body)

    assert response.status_code == 422
    assert problem_type(response) == "common/request-validation"
    assert kicker.calls == []


# - - - List and open - - -


async def test_list_returns_the_sources_in_order(
    api: AsyncClient, uow_factory: UowFactory, notebook: Notebook
) -> None:
    """NB-4: a plain array of SourceItem; `stale` and `has_guide` follow the source."""
    empty = await api.get(sources_url(notebook))
    first = await make_source(uow_factory, notebook, title="First")
    second = await make_source(
        uow_factory,
        notebook,
        title="Second",
        status=SourceStatus.STALE,
        guide=SourceGuide(summary="Plants."),
    )

    response = await api.get(sources_url(notebook))

    body = response.json()
    assert empty.status_code == 200 and empty.json() == []
    assert [item["id"] for item in body] == [str(first.id), str(second.id)]
    assert [set(item) for item in body] == [ITEM_KEYS, ITEM_KEYS]
    assert [item["stale"] for item in body] == [False, True]
    assert [item["has_guide"] for item in body] == [False, True]
    assert body[0]["word_count"] > 0 and body[0]["passage_count"] == 1


async def test_a_note_opens_with_its_guide_text_and_the_editable_flag(
    api: AsyncClient, uow_factory: UowFactory, notebook: Notebook
) -> None:
    """NB-4, NB-7: SourceDetail = SourceItem + guide, body_md, editable, citations."""
    note = await make_source(
        uow_factory,
        notebook,
        kind=SourceKind.NOTE,
        title="My note",
        body_md="# Cells",
        guide=SourceGuide(summary="Cells.", key_topics=["Cell"], questions=["Why?"]),
    )

    response = await api.get(sources_url(notebook, f"/{note.id}"))

    body = response.json()
    assert response.status_code == 200, response.text
    assert set(body) == DETAIL_KEYS
    assert body["id"] == str(note.id) and body["kind"] == "note"
    assert body["body_md"] == "# Cells" and body["editable"] is True
    assert body["guide"] == {
        "summary": "Cells.",
        "key_topics": ["Cell"],
        "questions": ["Why?"],
    }
    assert body["citations"] == [] and body["has_guide"] is True
    assert body["file"] is None


async def test_an_uploaded_file_source_carries_its_file_and_a_link_to_it(
    api: AsyncClient,
    uow_factory: UowFactory,
    world: World,
    student: Actor,
    notebook: Notebook,
) -> None:
    """SourceDetail.file names the upload; `file-url` presigns it for the member."""
    file = world.files.add_text(
        make_file(student.user_id, name="lab-setup.pdf"), "Text of the file."
    )
    source = await make_source(
        uow_factory,
        notebook,
        kind=SourceKind.FILE,
        title="lab-setup.pdf",
        ref={"file_id": str(file.id), "content_type": file.content_type},
    )

    detail = await api.get(sources_url(notebook, f"/{source.id}"))
    inline = await api.get(
        sources_url(notebook, f"/{source.id}/file-url"),
        params={"disposition": "inline"},
    )
    attachment = await api.get(sources_url(notebook, f"/{source.id}/file-url"))

    body = detail.json()
    assert detail.status_code == 200, detail.text
    assert set(body) == DETAIL_KEYS
    assert body["file"] == {
        "id": str(file.id),
        "name": "lab-setup.pdf",
        "content_type": "application/pdf",
        "byte_size": file.byte_size,
    }
    for response in (inline, attachment):
        assert response.status_code == 200, response.text
        assert set(response.json()) == {"url", "expires_at"}
        assert response.json()["url"] == f"https://files.test/{file.id}"


async def test_the_file_link_is_hidden_with_the_notebook_and_for_sources_without_a_file(
    api: AsyncClient,
    uow_factory: UowFactory,
    world: World,
    other_student: Actor,
    notebook: Notebook,
    theirs: Notebook,
) -> None:
    """A pasted text has no file; another student's notebook is a 404 (not 403)."""
    text = await make_source(uow_factory, notebook, kind=SourceKind.TEXT)
    file = world.files.add_text(make_file(other_student.user_id), "Not yours.")
    foreign = await make_source(
        uow_factory, theirs, kind=SourceKind.FILE, ref={"file_id": str(file.id)}
    )

    no_file = await api.get(sources_url(notebook, f"/{text.id}/file-url"))
    hidden = await api.get(sources_url(theirs, f"/{foreign.id}/file-url"))

    assert no_file.status_code == 404, no_file.text
    assert hidden.status_code == 404, hidden.text


async def test_a_source_with_citations_is_not_editable_and_lists_them(
    api: AsyncClient, uow_factory: UowFactory, notebook: Notebook
) -> None:
    """NB-7: a saved chat answer keeps its citations and cannot be edited."""
    cited = await make_source(uow_factory, notebook, title="Biology 10.pdf")
    citation = Citation(
        n=1,
        passage_id=new_id(),
        source_id=cited.id,
        source_title="Biology 10.pdf",
        source_kind=SourceKind.FILE,
        page=12,
        snippet="Plants make sugar.",
    )
    saved = await make_source(
        uow_factory,
        notebook,
        kind=SourceKind.NOTE,
        title="From chat",
        body_md="Plants make sugar ⟦1⟧.",
        citations=[citation],
    )
    other = await make_source(uow_factory, notebook, kind=SourceKind.FLASHCARD_SET)

    note = (await api.get(sources_url(notebook, f"/{saved.id}"))).json()
    cards = (await api.get(sources_url(notebook, f"/{other.id}"))).json()

    assert note["editable"] is False
    assert note["citations"] == [
        {
            "n": 1,
            "passage_id": str(citation.passage_id),
            "source_id": str(cited.id),
            "source_title": "Biology 10.pdf",
            "source_kind": "file",
            "page": 12,
            "snippet": "Plants make sugar.",
        }
    ]
    assert cards["editable"] is False and cards["guide"] is None
    assert cards["body_md"] is None and cards["citations"] == []


# - - - Edit - - -


async def test_patch_changes_only_the_keys_that_were_sent(
    api: AsyncClient, uow_factory: UowFactory, notebook: Notebook
) -> None:
    """NB-4, NB-5: an absent key is kept (not sent as null); the answer is an item."""
    source = await make_source(uow_factory, notebook, title="Biology")
    url = sources_url(notebook, f"/{source.id}")

    unticked = await api.patch(url, json={"selected": False})
    renamed = await api.patch(url, json={"title": "  Cell   biology "})
    untouched = await api.patch(url, json={})

    assert unticked.status_code == 200, unticked.text
    assert set(unticked.json()) == ITEM_KEYS
    assert unticked.json()["selected"] is False
    assert unticked.json()["title"] == "Biology"
    assert renamed.json()["title"] == "Cell biology"
    assert renamed.json()["selected"] is False
    assert untouched.json() == renamed.json()


async def test_a_new_text_puts_a_note_back_to_pending_and_starts_the_processing(
    api: AsyncClient,
    uow_factory: UowFactory,
    notebook: Notebook,
    kicker: FakeTaskKicker,
) -> None:
    """NB-4: `body_md` re-chunks the note: `pending`, one job, new text on open."""
    note = await make_source(
        uow_factory, notebook, kind=SourceKind.NOTE, body_md="Old text."
    )
    url = sources_url(notebook, f"/{note.id}")

    response = await api.patch(url, json={"body_md": "New text."})

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "pending"
    assert kicker.calls == [(PROCESS_TASK, {"source_id": str(note.id)})]
    assert (await api.get(url)).json()["body_md"] == "New text."


async def test_a_text_cannot_be_edited_on_a_file_or_while_processing(
    api: AsyncClient,
    uow_factory: UowFactory,
    notebook: Notebook,
    kicker: FakeTaskKicker,
) -> None:
    """NB-4, § 4.7: `invalid-options` for a file, `source-not-ready` while pending."""
    file = await make_source(uow_factory, notebook, kind=SourceKind.FILE)
    busy = await make_source(
        uow_factory,
        notebook,
        kind=SourceKind.TEXT,
        texts=(),
        status=SourceStatus.PENDING,
        body_md="Waiting.",
    )

    on_file = await api.patch(
        sources_url(notebook, f"/{file.id}"), json={"body_md": "Text"}
    )
    on_busy = await api.patch(
        sources_url(notebook, f"/{busy.id}"), json={"body_md": "Text"}
    )

    assert on_file.status_code == 422
    assert problem_type(on_file) == "notebooks/invalid-options"
    assert on_busy.status_code == 409
    assert problem_type(on_busy) == "notebooks/source-not-ready"
    assert kicker.calls == []


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ({"title": "x" * 256}, "common/request-validation"),
        ({"selected": "banana"}, "common/request-validation"),
        ({"title": ""}, "notebooks/invalid-options"),
        ({"title": None}, "notebooks/invalid-options"),
        ({"selected": None}, "notebooks/invalid-options"),
        ({"body_md": None}, "notebooks/invalid-options"),
    ],
)
async def test_patch_rejects_a_bad_body_with_422(
    api: AsyncClient,
    uow_factory: UowFactory,
    notebook: Notebook,
    body: dict[str, Any],
    expected: str,
) -> None:
    """NB-4: schema errors and use case errors are both `422` problem+json."""
    source = await make_source(uow_factory, notebook, kind=SourceKind.NOTE)

    response = await api.patch(sources_url(notebook, f"/{source.id}"), json=body)

    assert response.status_code == 422
    assert problem_type(response) == expected


# - - - Select - - -


async def test_select_without_ids_ticks_or_unticks_every_source(
    api: AsyncClient, uow_factory: UowFactory, notebook: Notebook
) -> None:
    """NB-5: `{selected}` alone hits all sources; the answer lists them all."""
    made = [await make_source(uow_factory, notebook, title=f"S{n}") for n in range(3)]

    off = await api.post(sources_url(notebook, "/select"), json={"selected": False})
    counted = (await api.get(f"/v1/notebooks/{notebook.id}")).json()
    on = await api.post(sources_url(notebook, "/select"), json={"selected": True})

    assert off.status_code == 200, off.text
    assert [item["id"] for item in off.json()] == [str(s.id) for s in made]
    assert [set(item) for item in off.json()] == [ITEM_KEYS] * 3
    assert [item["selected"] for item in off.json()] == [False] * 3
    assert counted["selected_source_count"] == 0 and counted["ready_source_count"] == 3
    assert [item["selected"] for item in on.json()] == [True] * 3


async def test_select_with_ids_changes_only_those_sources(
    api: AsyncClient, uow_factory: UowFactory, student: Actor, notebook: Notebook
) -> None:
    """NB-5: ids of other notebooks are ignored; an empty list changes nothing."""
    first = await make_source(uow_factory, notebook, selected=False)
    second = await make_source(uow_factory, notebook, selected=False)
    elsewhere = await make_notebook(uow_factory, student.user_id)
    stranger = await make_source(uow_factory, elsewhere, selected=False)
    url = sources_url(notebook, "/select")

    nothing = await api.post(url, json={"selected": True, "ids": []})
    one = await api.post(
        url, json={"selected": True, "ids": [str(second.id), str(stranger.id)]}
    )

    assert [item["selected"] for item in nothing.json()] == [False, False]
    assert [item["selected"] for item in one.json()] == [False, True]
    assert [item["id"] for item in one.json()] == [str(first.id), str(second.id)]
    other_list = (await api.get(sources_url(elsewhere))).json()
    assert [item["selected"] for item in other_list] == [False]


@pytest.mark.parametrize(
    "body", [{}, {"selected": "banana"}, {"selected": True, "ids": ["nope"]}]
)
async def test_select_rejects_a_bad_body_with_422(
    api: AsyncClient, notebook: Notebook, body: dict[str, Any]
) -> None:
    """NB-5: `selected` is required and `ids` are UUIDs."""
    response = await api.post(sources_url(notebook, "/select"), json=body)

    assert response.status_code == 422
    assert problem_type(response) == "common/request-validation"


# - - - Sync and remove - - -


async def test_sync_queues_a_new_read_of_a_flash_card_set_source(
    api: AsyncClient,
    uow_factory: UowFactory,
    notebook: Notebook,
    kicker: FakeTaskKicker,
) -> None:
    """NB-3: a source that can change is read again: SourceItem, one job."""
    source = await make_source(uow_factory, notebook, kind=SourceKind.FLASHCARD_SET)
    url = sources_url(notebook, f"/{source.id}/sync")

    response = await api.post(url)
    again = await api.post(url)

    assert response.status_code == 200, response.text
    assert set(response.json()) == ITEM_KEYS
    assert response.json()["status"] == "pending"
    assert kicker.calls == [(PROCESS_TASK, {"source_id": str(source.id)})]
    assert again.status_code == 409
    assert problem_type(again) == "notebooks/source-not-ready"


async def test_sync_leaves_pasted_text_alone(
    api: AsyncClient,
    uow_factory: UowFactory,
    notebook: Notebook,
    kicker: FakeTaskKicker,
) -> None:
    """NB-3: pasted text has nothing to read again: the source comes back as it is."""
    source = await make_source(uow_factory, notebook, kind=SourceKind.TEXT)

    response = await api.post(sources_url(notebook, f"/{source.id}/sync"))

    assert response.status_code == 200
    assert response.json()["status"] == "ready"
    assert kicker.calls == []


async def test_remove_answers_204_without_a_body_and_drops_the_source(
    api: AsyncClient, uow_factory: UowFactory, notebook: Notebook
) -> None:
    """NB-4: `204`; the source is gone from the list and from the page."""
    source = await make_source(uow_factory, notebook)
    kept = await make_source(uow_factory, notebook)
    url = sources_url(notebook, f"/{source.id}")

    deleted = await api.delete(url)
    opened = await api.get(url)
    listed = (await api.get(sources_url(notebook))).json()
    counted = (await api.get(f"/v1/notebooks/{notebook.id}")).json()

    assert deleted.status_code == 204 and deleted.content == b""
    assert opened.status_code == 404 and problem_type(opened) == "notebooks/not-found"
    assert [item["id"] for item in listed] == [str(kept.id)]
    assert counted["source_count"] == 1


# - - - Passages - - -


async def test_passages_are_paged_in_reading_order(
    api: AsyncClient, uow_factory: UowFactory, notebook: Notebook
) -> None:
    """NB-7: `Page<PassageItem>` with a cursor; the default page is 60."""
    source = await make_source(uow_factory, notebook, texts=TEXTS)
    url = sources_url(notebook, f"/{source.id}/passages")

    first = (await api.get(url, params={"limit": 2})).json()
    second = (
        await api.get(url, params={"limit": 2, "cursor": first["next_cursor"]})
    ).json()
    last = (
        await api.get(url, params={"limit": 2, "cursor": second["next_cursor"]})
    ).json()
    whole = (await api.get(url)).json()

    assert set(first) == {"items", "next_cursor"}
    assert [set(p) for p in first["items"]] == [PASSAGE_KEYS] * 2
    assert [p["seq"] for p in first["items"]] == [1, 2]
    assert [p["seq"] for p in second["items"]] == [3, 4]
    assert [p["seq"] for p in last["items"]] == [5] and last["next_cursor"] is None
    assert [p["text"] for p in whole["items"]] == list(TEXTS)
    assert whole["next_cursor"] is None
    assert first["items"][0]["page"] is None and first["items"][0]["heading"] is None


@pytest.mark.parametrize(
    ("params", "expected"),
    [
        ({"limit": 0}, "common/request-validation"),
        ({"limit": 201}, "common/request-validation"),
        ({"cursor": "not-a-cursor"}, "common/validation"),
    ],
)
async def test_passages_reject_a_bad_page_request_with_422(
    api: AsyncClient,
    uow_factory: UowFactory,
    notebook: Notebook,
    params: dict[str, Any],
    expected: str,
) -> None:
    """NB-7: the page size is 1 to 200 and the cursor must be ours."""
    source = await make_source(uow_factory, notebook, texts=TEXTS)

    response = await api.get(
        sources_url(notebook, f"/{source.id}/passages"), params=params
    )

    assert response.status_code == 422
    assert problem_type(response) == expected


async def passage_ids(
    api: AsyncClient, notebook: Notebook, source_id: UUID
) -> list[str]:
    """The passage ids of a source, by `seq`."""
    page = (await api.get(sources_url(notebook, f"/{source_id}/passages"))).json()
    return [p["id"] for p in page["items"]]


async def test_a_passage_comes_with_its_source_and_its_neighbours(
    api: AsyncClient, uow_factory: UowFactory, notebook: Notebook
) -> None:
    """NB-6, NB-7: PassageDetail with `?context` passages on each side (default 2)."""
    source = await make_source(uow_factory, notebook, title="Biology", texts=TEXTS)
    ids = await passage_ids(api, notebook, source.id)
    url = f"/v1/notebooks/{notebook.id}/passages/{ids[2]}"

    default = await api.get(url)
    one = await api.get(url, params={"context": 1})
    none = await api.get(url, params={"context": 0})
    edge = await api.get(f"/v1/notebooks/{notebook.id}/passages/{ids[0]}")

    body = default.json()
    assert default.status_code == 200, default.text
    assert set(body) == {"passage", "source", "before", "after"}
    assert set(body["passage"]) == PASSAGE_KEYS
    assert body["passage"]["id"] == ids[2] and body["passage"]["text"] == TEXTS[2]
    assert body["source"] == {"id": str(source.id), "title": "Biology", "kind": "text"}
    assert [p["id"] for p in body["before"]] == ids[0:2]
    assert [p["id"] for p in body["after"]] == ids[3:5]
    assert [set(p) for p in body["before"] + body["after"]] == [PASSAGE_KEYS] * 4
    assert [p["id"] for p in one.json()["before"]] == [ids[1]]
    assert [p["id"] for p in one.json()["after"]] == [ids[3]]
    assert none.json()["before"] == [] and none.json()["after"] == []
    assert edge.json()["before"] == [] and len(edge.json()["after"]) == 2


@pytest.mark.parametrize("context", [-1, 6, "many"])
async def test_a_passage_rejects_a_bad_context_with_422(
    api: AsyncClient, uow_factory: UowFactory, notebook: Notebook, context: Any
) -> None:
    """NB-7: `context` is 0 to 5."""
    source = await make_source(uow_factory, notebook, texts=TEXTS)
    ids = await passage_ids(api, notebook, source.id)

    response = await api.get(
        f"/v1/notebooks/{notebook.id}/passages/{ids[0]}", params={"context": context}
    )

    assert response.status_code == 422
    assert problem_type(response) == "common/request-validation"


async def test_a_passage_of_another_notebook_is_not_found(
    api: AsyncClient, uow_factory: UowFactory, student: Actor, notebook: Notebook
) -> None:
    """NB-15: a passage is only readable through its own notebook."""
    elsewhere = await make_notebook(uow_factory, student.user_id)
    source = await make_source(uow_factory, elsewhere, texts=TEXTS)
    ids = await passage_ids(api, elsewhere, source.id)

    wrong = await api.get(f"/v1/notebooks/{notebook.id}/passages/{ids[0]}")
    missing = await api.get(f"/v1/notebooks/{notebook.id}/passages/{new_id()}")

    assert wrong.status_code == 404 and missing.status_code == 404
    assert problem_type(wrong) == problem_type(missing) == "notebooks/not-found"


# - - - Another student's notebook, wrong role - - -


async def test_the_sources_of_another_students_notebook_are_a_404_everywhere(
    api: AsyncClient,
    uow_factory: UowFactory,
    other_student: Actor,
    theirs: Notebook,
    kicker: FakeTaskKicker,
) -> None:
    """NB-15: every source and passage route answers `404 notebooks/not-found`."""
    source = await make_source(uow_factory, theirs, texts=TEXTS)
    own = sources_url(theirs, f"/{source.id}")
    passage = new_id()

    responses = [
        await api.get(sources_url(theirs)),
        await api.post(sources_url(theirs), json={"items": [text_item()]}),
        await api.post(sources_url(theirs, "/select"), json={"selected": False}),
        await api.get(own),
        await api.patch(own, json={"title": "Mine"}),
        await api.post(f"{own}/sync"),
        await api.delete(own),
        await api.get(f"{own}/passages"),
        await api.get(f"/v1/notebooks/{theirs.id}/passages/{passage}"),
    ]

    assert [r.status_code for r in responses] == [404] * 9
    assert {problem_type(r) for r in responses} == {"notebooks/not-found"}
    assert kicker.calls == []


async def test_a_source_is_only_reachable_through_its_own_notebook(
    api: AsyncClient, uow_factory: UowFactory, student: Actor, notebook: Notebook
) -> None:
    """NB-15: the source id of one notebook under another notebook's path is a 404."""
    elsewhere = await make_notebook(uow_factory, student.user_id)
    source = await make_source(uow_factory, elsewhere)

    response = await api.get(sources_url(notebook, f"/{source.id}"))

    assert response.status_code == 404
    assert problem_type(response) == "notebooks/not-found"


@pytest.mark.parametrize("role", [Role.TEACHER, Role.ADMIN])
async def test_only_students_may_use_sources(
    api: AsyncClient,
    current: dict[str, Actor],
    make_actor: Callable[..., Actor],
    uow_factory: UowFactory,
    notebook: Notebook,
    role: Role,
) -> None:
    """NB-1, LMS-AI 3.1: on a student's notebook staff get the `404` of a missing
    notebook on every source and passage endpoint."""
    source = await make_source(uow_factory, notebook, texts=TEXTS)
    current["actor"] = make_actor(role)
    own = sources_url(notebook, f"/{source.id}")

    responses = [
        await api.get(sources_url(notebook)),
        await api.post(sources_url(notebook), json={"items": [text_item()]}),
        await api.post(sources_url(notebook, "/select"), json={"selected": True}),
        await api.get(own),
        await api.patch(own, json={"selected": False}),
        await api.post(f"{own}/sync"),
        await api.delete(own),
        await api.get(f"{own}/passages"),
        await api.get(f"/v1/notebooks/{notebook.id}/passages/{new_id()}"),
    ]

    assert [r.status_code for r in responses] == [404] * 9
    assert {problem_type(r) for r in responses} == {"notebooks/not-found"}
