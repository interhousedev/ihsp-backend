"""LIB-13, LIB-14: the librarian and administration endpoints."""

import datetime as dt
from collections.abc import Awaitable, Callable
from uuid import UUID

from app.modules.library.domain.enums import ItemStatus, ReportReason, UploaderRole
from app.modules.library.domain.moderation_entities import Report
from app.modules.library.ports.unit_of_work import UowFactory
from app.modules.library.wiring import LibraryServices
from app.shared.actor import Actor
from app.shared.ids import new_id
from tests.fakes.clock import FixedClock

import pytest
from httpx import AsyncClient

Api = Callable[[Actor | None], Awaitable[AsyncClient]]
MakePending = Callable[..., Awaitable[UUID]]
SetStatus = Callable[..., Awaitable[None]]


# - - - Queue - - -


async def test_the_queue_row_has_the_shape_of_the_contract(
    api: Api, student: Actor, other_librarian: Actor, make_pending: MakePending
) -> None:
    """LIB-13: `ManageQueueRow`: optional keys appear only when they apply."""
    item_id = await make_pending(student)
    client = await api(other_librarian)

    response = await client.get("/v1/manage/library/queue", params={"tab": "review"})

    assert response.status_code == 200
    page = response.json()
    assert page["next_cursor"] is None
    (row,) = page["items"]
    assert row["item"]["id"] == str(item_id)
    assert row["kind"] == "student_material"
    assert row["uploader"] == {"name": "Aziza K.", "cohort": "2025", "role": "student"}
    assert row["scan"] == {"findings": []}
    assert row["reports"] == []
    assert row["submitted_at"].startswith("2026-10-06T09:00:00")
    assert "report_ids" not in row
    assert "suggestion" not in row


async def test_report_rows_list_ids_and_reasons_but_never_reporters(
    api: Api,
    student: Actor,
    other_librarian: Actor,
    make_pending: MakePending,
    set_status: SetStatus,
    uow_factory: UowFactory,
    clock: FixedClock,
) -> None:
    """LIB-14: `report_ids` and `reports` per reason."""
    item_id = await make_pending(student)
    await set_status(item_id, ItemStatus.PUBLISHED)
    reporter = new_id()
    report = Report(
        id=new_id(),
        item_id=item_id,
        reporter_id=reporter,
        reporter_role=UploaderRole.STUDENT,
        reason=ReportReason.COPYRIGHT,
        created_at=clock.now(),
    )
    async with uow_factory() as uow:
        await uow.moderation.add_report(report)
        await uow.commit()
    client = await api(other_librarian)

    response = await client.get("/v1/manage/library/queue", params={"tab": "reports"})

    (row,) = response.json()["items"]
    assert row["kind"] == "report"
    assert row["reports"] == [{"reason": "copyright", "count": 1}]
    assert row["report_ids"] == [str(report.id)]
    assert str(reporter) not in response.text
    assert "uploader" in row


async def test_suggestion_rows_have_a_card_without_an_id(
    api: Api, student: Actor, other_librarian: Actor
) -> None:
    """LIB-2: the suggestions tab."""
    await (await api(student)).post(
        "/v1/library/suggestions", json={"title": "Atom physics", "note": "Good"}
    )
    client = await api(other_librarian)

    response = await client.get(
        "/v1/manage/library/queue", params={"tab": "suggestions"}
    )

    (row,) = response.json()["items"]
    assert row["item"]["id"] is None and row["item"]["slug"] is None
    assert row["kind"] == "suggestion"
    assert row["suggestion"]["title"] == "Atom physics"
    assert row["suggestion"]["user_name"] == "Aziza K., 2025"
    assert set(row["suggestion"]) == {
        "id", "title", "url", "note", "user_name", "book",
    }  # fmt: skip
    assert "report_ids" not in row


async def test_a_suggestion_from_the_editor_shows_its_form_to_librarians(
    api: Api, student: Actor, other_librarian: Actor, library: LibraryServices
) -> None:
    """The queue row names the authors; `GET .../suggestions/{id}` returns the form."""
    subject = (
        await library.taxonomy.create_subject.execute(
            other_librarian, name={"en": "Economics"}
        )
    ).id
    form = {
        "title": "Money and banks",
        "authors": ["Paul Samuelson"],
        "tags": ["economics"],
        "language": "en",
        "type": "textbook",
        "subjects": [{"subject_id": str(subject), "role": "textbook"}],
    }
    created = await (await api(student)).post(
        "/v1/library/suggestions",
        json={"title": "Money and banks", "note": "Please", "book": form},
    )
    librarian_client = await api(other_librarian)

    queue = await librarian_client.get(
        "/v1/manage/library/queue", params={"tab": "suggestions"}
    )
    (row,) = queue.json()["items"]
    one = await librarian_client.get(
        f"/v1/manage/library/suggestions/{row['suggestion']['id']}"
    )
    refused = await (await api(student)).get(
        f"/v1/manage/library/suggestions/{row['suggestion']['id']}"
    )

    assert created.status_code == 201
    assert row["item"]["author_label"] == "Paul Samuelson"
    assert row["suggestion"]["book"]["tags"] == ["economics"]
    assert one.json()["status"] == "new" and one.json()["note"] == "Please"
    assert one.json()["book"]["authors"] == ["Paul Samuelson"]
    assert refused.status_code == 403


async def test_an_unknown_tab_is_422(api: Api, other_librarian: Actor) -> None:
    """LIB-13: only the five tabs exist."""
    client = await api(other_librarian)

    response = await client.get("/v1/manage/library/queue", params={"tab": "all"})

    assert response.status_code == 422


# - - - Decisions - - -


async def test_approve_publishes_and_returns_the_item_detail(
    api: Api, student: Actor, other_librarian: Actor, make_pending: MakePending
) -> None:
    """LIB-13: `POST .../items/{id}/approve`."""
    item_id = await make_pending(student)
    client = await api(other_librarian)

    response = await client.post(f"/v1/manage/library/items/{item_id}/approve")

    assert response.status_code == 200
    assert response.json()["status"] == "published"
    assert response.json()["can"]["edit"] is True


@pytest.mark.parametrize(
    ("action", "status"),
    [
        ("request-changes", "changes_requested"),
        ("reject", "rejected"),
    ],
)
async def test_decisions_with_a_reason_return_status_reason_and_note(
    api: Api,
    student: Actor,
    other_librarian: Actor,
    make_pending: MakePending,
    action: str,
    status: str,
) -> None:
    """LIB-13: reason code and note come back on the detail."""
    item_id = await make_pending(student)
    client = await api(other_librarian)

    response = await client.post(
        f"/v1/manage/library/items/{item_id}/{action}",
        json={"reason": "low_quality", "note": "Add the title page"},
    )

    body = response.json()
    assert response.status_code == 200
    assert (body["status"], body["status_reason"], body["status_note"]) == (
        status,
        "low_quality",
        "Add the title page",
    )


async def test_a_decision_without_a_reason_is_a_problem(
    api: Api, student: Actor, other_librarian: Actor, make_pending: MakePending
) -> None:
    """LIB-13: `422 library/reason-required`."""
    item_id = await make_pending(student)
    client = await api(other_librarian)

    response = await client.post(f"/v1/manage/library/items/{item_id}/reject")

    assert response.status_code == 422
    assert response.json()["type"] == "library/reason-required"


async def test_approving_your_own_upload_is_forbidden(
    api: Api, librarian: Actor, make_pending: MakePending
) -> None:
    """LIB-13: `403 library/own-item`."""
    item_id = await make_pending(librarian)
    client = await api(librarian)

    response = await client.post(f"/v1/manage/library/items/{item_id}/approve")

    assert response.status_code == 403
    assert response.json()["type"] == "library/own-item"


async def test_an_illegal_arrow_is_a_conflict(
    api: Api,
    student: Actor,
    other_librarian: Actor,
    make_pending: MakePending,
    set_status: SetStatus,
) -> None:
    """LIB-13: `409 library/invalid-transition` with status and action."""
    item_id = await make_pending(student)
    await set_status(item_id, ItemStatus.PUBLISHED)
    client = await api(other_librarian)

    response = await client.post(f"/v1/manage/library/items/{item_id}/approve")

    assert response.status_code == 409
    assert response.json()["type"] == "library/invalid-transition"
    assert response.json()["params"] == {"status": "published", "action": "approve"}


async def test_an_unknown_action_is_422_and_a_draft_is_404(
    api: Api,
    student: Actor,
    other_librarian: Actor,
    make_draft: Callable[..., Awaitable[UUID]],
) -> None:
    """LIB-13: drafts are invisible to librarians."""
    draft = await make_draft(student)
    client = await api(other_librarian)

    unknown = await client.post(f"/v1/manage/library/items/{draft}/delete")
    hidden = await client.post(f"/v1/manage/library/items/{draft}/approve")

    assert unknown.status_code == 422
    assert hidden.status_code == 404
    assert hidden.json()["type"] == "library/not-found"


async def test_resolve_answers_no_content(
    api: Api,
    student: Actor,
    other_librarian: Actor,
    make_pending: MakePending,
    set_status: SetStatus,
    uow_factory: UowFactory,
    clock: FixedClock,
) -> None:
    """LIB-14: `204` for `resolve`, and the item is held."""
    item_id = await make_pending(student)
    await set_status(item_id, ItemStatus.PUBLISHED)
    report = Report(
        id=new_id(),
        item_id=item_id,
        reporter_id=new_id(),
        reporter_role=UploaderRole.STUDENT,
        reason=ReportReason.SPAM,
        created_at=clock.now(),
    )
    async with uow_factory() as uow:
        await uow.moderation.add_report(report)
        await uow.commit()
    client = await api(other_librarian)

    response = await client.post(
        f"/v1/manage/library/reports/{report.id}/resolve", json={"action": "hold"}
    )
    bad = await client.post(
        f"/v1/manage/library/reports/{report.id}/resolve", json={"action": "nuke"}
    )
    missing = await client.post(
        f"/v1/manage/library/reports/{new_id()}/resolve", json={"action": "hold"}
    )

    assert response.status_code == 204
    assert bad.status_code == 422
    assert missing.status_code == 404
    assert missing.json()["type"] == "library/report-not-found"


async def test_a_suggestion_can_be_accepted_over_http(
    api: Api, student: Actor, other_librarian: Actor
) -> None:
    """LIB-2: `POST .../suggestions/{id}/accept` answers `204`."""
    await (await api(student)).post("/v1/library/suggestions", json={"title": "Atom"})
    client = await api(other_librarian)
    queue = await client.get("/v1/manage/library/queue", params={"tab": "suggestions"})
    suggestion_id = queue.json()["items"][0]["suggestion"]["id"]

    accepted = await client.post(
        f"/v1/manage/library/suggestions/{suggestion_id}/accept"
    )
    again = await client.post(f"/v1/manage/library/suggestions/{suggestion_id}/decline")
    odd = await client.post(f"/v1/manage/library/suggestions/{suggestion_id}/ignore")

    assert accepted.status_code == 204
    assert again.status_code == 409
    assert odd.status_code == 422


# - - - Sanctions - - -


async def test_an_admin_creates_and_lists_sanctions(
    api: Api, student: Actor, admin: Actor, clock: FixedClock
) -> None:
    """LIB-14: `201` with the `Sanction` of the contract; the list filters by user."""
    client = await api(admin)
    until = (clock.now() + dt.timedelta(days=3)).isoformat()

    created = await client.post(
        "/v1/admin/library/sanctions",
        json={
            "user_id": str(student.user_id),
            "kind": "upload_ban",
            "until": until,
            "reason": "repeated copyright reports",
        },
    )
    listed = await client.get(
        "/v1/admin/library/sanctions", params={"user_id": str(student.user_id)}
    )
    other = await client.get(
        "/v1/admin/library/sanctions", params={"user_id": str(new_id())}
    )

    assert created.status_code == 201
    body = created.json()
    assert set(body) == {
        "id",
        "user_id",
        "kind",
        "until",
        "reason",
        "item_id",
        "created_at",
    }
    assert body["kind"] == "upload_ban"
    assert body["item_id"] is None
    assert listed.json() == [body]
    assert other.json() == []


async def test_a_warning_needs_no_end_date_and_bad_bodies_are_422(
    api: Api, student: Actor, admin: Actor
) -> None:
    """LIB-14: required fields are validated."""
    client = await api(admin)

    ok = await client.post(
        "/v1/admin/library/sanctions",
        json={
            "user_id": str(student.user_id),
            "kind": "warning",
            "reason": "Please read",
        },
    )
    no_reason = await client.post(
        "/v1/admin/library/sanctions",
        json={"user_id": str(student.user_id), "kind": "warning", "reason": ""},
    )
    bad_kind = await client.post(
        "/v1/admin/library/sanctions",
        json={"user_id": str(student.user_id), "kind": "exile", "reason": "x"},
    )

    assert ok.status_code == 201
    assert ok.json()["until"] is None
    assert (no_reason.status_code, bad_kind.status_code) == (422, 422)


# - - - Roles - - -

STAFF_ONLY = [
    ("GET", "/v1/manage/library/queue?tab=review"),
    ("POST", "/v1/manage/library/items/{id}/approve"),
    ("POST", "/v1/manage/library/reports/{id}/resolve"),
    ("POST", "/v1/manage/library/suggestions/{id}/accept"),
]
ADMIN_ONLY = [
    ("GET", "/v1/admin/library/sanctions"),
    ("POST", "/v1/admin/library/sanctions"),
]


@pytest.mark.parametrize(("method", "path"), STAFF_ONLY + ADMIN_ONLY)
async def test_endpoints_without_a_token_are_401(
    api: Api, method: str, path: str
) -> None:
    """LIB-2: no token, no entry."""
    client = await api(None)

    response = await client.request(method, path.format(id=new_id()), json={})

    assert response.status_code == 401


@pytest.mark.parametrize(("method", "path"), STAFF_ONLY)
@pytest.mark.parametrize("who", ["student", "teacher"])
async def test_students_and_teachers_get_403_on_librarian_endpoints(
    api: Api, request: pytest.FixtureRequest, method: str, path: str, who: str
) -> None:
    """LIB-2: roles librarian or admin are required."""
    actor: Actor = request.getfixturevalue(who)
    client = await api(actor)

    response = await client.request(
        method, path.format(id=new_id()), json={"action": "hold"}
    )

    assert response.status_code == 403


@pytest.mark.parametrize(("method", "path"), ADMIN_ONLY)
@pytest.mark.parametrize("who", ["student", "teacher", "other_librarian"])
async def test_only_administration_reaches_sanctions(
    api: Api, request: pytest.FixtureRequest, method: str, path: str, who: str
) -> None:
    """LIB-14: librarians cannot ban."""
    actor: Actor = request.getfixturevalue(who)
    client = await api(actor)

    response = await client.request(method, path, json={})

    assert response.status_code == 403


async def test_the_admin_may_use_librarian_endpoints(
    api: Api, admin: Actor, student: Actor, make_pending: MakePending
) -> None:
    """LIB-2: Administration has every librarian power."""
    item_id = await make_pending(student)
    client = await api(admin)

    queue = await client.get("/v1/manage/library/queue", params={"tab": "review"})
    approved = await client.post(f"/v1/manage/library/items/{item_id}/approve")

    assert queue.status_code == 200 and len(queue.json()["items"]) == 1
    assert approved.status_code == 200
