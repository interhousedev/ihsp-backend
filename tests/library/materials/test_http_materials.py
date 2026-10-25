"""LIB-13: the upload endpoints: shapes, status codes, auth and IDOR."""

import datetime as dt
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

from app.modules.library.domain.enums import ItemStatus, SanctionKind
from app.modules.library.domain.moderation_entities import Sanction
from app.modules.library.ports.unit_of_work import UowFactory
from app.shared.actor import Actor
from app.shared.ids import new_id
from tests.fakes.library.material_files import MaterialFilesApi

import pytest
from httpx import AsyncClient

Api = Callable[[Actor | None], Awaitable[AsyncClient]]
MakeDraft = Callable[..., Awaitable[UUID]]
SetStatus = Callable[..., Awaitable[None]]


def payload(physics: UUID, **changes: Any) -> dict[str, Any]:
    """A valid `MaterialInput` body."""
    body: dict[str, Any] = {
        "title": "Kinematics cheat sheet",
        "description": "Formulas of motion.",
        "subject_ids": [str(physics)],
        "topic_ids": [],
        "years_of_study": [1],
        "type": "formula_sheet",
        "language": "uz_latn",
        "licence": "all_rights_reserved",
        "attested": True,
    }
    return body | changes


async def test_create_returns_a_draft_item_detail(
    api: Api, student: Actor, physics: UUID
) -> None:
    """LIB-13: `201` and the `ItemDetail` of the contract."""
    client = await api(student)

    response = await client.post("/v1/library/materials", json=payload(physics))

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "draft"
    assert body["kind"] == "material"
    assert body["tag"] == {"source": "material", "label": "Material"}
    assert body["material"] == {
        "uploader_name": "Aziza K.",
        "uploader_cohort": "2025",
        "uploader_role": "student",
    }
    assert body["can"]["edit"] is True
    assert body["files"] == []
    assert [s["name"] for s in body["subjects"]] == ["Physics"]


async def test_the_whole_upload_flow_over_http(
    api: Api, student: Actor, physics: UUID, files_api: MaterialFilesApi
) -> None:
    """LIB-13: create, attach, submit (`202`), patch, list uploads, withdraw."""
    client = await api(student)
    created = await client.post("/v1/library/materials", json=payload(physics))
    item_id = created.json()["id"]
    pdf = files_api.upload(student.user_id, pages=4)

    attached = await client.post(
        f"/v1/library/materials/{item_id}/files", json={"file_ids": [str(pdf)]}
    )
    submitted = await client.post(f"/v1/library/materials/{item_id}/submit")
    patched = await client.patch(
        f"/v1/library/materials/{item_id}", json={"title": "Kinematics v2"}
    )
    uploads = await client.get("/v1/me/library/uploads")
    deleted = await client.delete(f"/v1/library/materials/{item_id}")

    assert attached.status_code == 200
    assert [f["id"] for f in attached.json()["files"]] == [str(pdf)]
    assert attached.json()["files"][0]["format"] == "pdf"
    assert submitted.status_code == 202
    assert submitted.json()["status"] == "pending_review"
    assert patched.json()["title"] == "Kinematics v2"
    rows = uploads.json()["items"]
    assert uploads.json()["next_cursor"] is None
    assert rows[0]["status"] == "pending_review"
    assert rows[0]["queue_position"] == 1
    assert rows[0]["reason"] is None
    assert rows[0]["item"]["id"] == item_id
    assert deleted.status_code == 204
    assert deleted.content == b""


async def test_a_teacher_submit_answers_published(
    api: Api, teacher: Actor, physics: UUID, files_api: MaterialFilesApi
) -> None:
    """LIB-13: teachers publish at once."""
    client = await api(teacher)
    created = await client.post("/v1/library/materials", json=payload(physics))
    item_id = created.json()["id"]
    pdf = files_api.upload(teacher.user_id)
    await client.post(
        f"/v1/library/materials/{item_id}/files", json={"file_ids": [str(pdf)]}
    )

    response = await client.post(f"/v1/library/materials/{item_id}/submit")

    assert response.status_code == 202
    assert response.json()["status"] == "published"


async def test_a_version_answers_created(
    api: Api,
    student: Actor,
    physics: UUID,
    make_draft: MakeDraft,
    set_status: SetStatus,
) -> None:
    """LIB-13: `201` for a new version of a published material."""
    item_id = await make_draft(student)
    await set_status(item_id, ItemStatus.PUBLISHED)
    client = await api(student)

    response = await client.post(
        f"/v1/library/materials/{item_id}/versions", json=payload(physics)
    )

    assert response.status_code == 201
    assert response.json()["status"] == "draft"
    assert response.json()["id"] != str(item_id)


async def test_the_uploads_list_filters_by_status_and_pages(
    api: Api, student: Actor, make_draft: MakeDraft
) -> None:
    """LIB-13: `?status=` and `?limit=` with a cursor."""
    ids = [await make_draft(student, title=f"M{i}") for i in range(3)]
    client = await api(student)

    first = await client.get("/v1/me/library/uploads", params={"limit": 2})
    rest = await client.get(
        "/v1/me/library/uploads",
        params={"limit": 2, "cursor": first.json()["next_cursor"]},
    )
    none = await client.get("/v1/me/library/uploads", params={"status": "published"})

    assert len(first.json()["items"]) == 2
    assert len(rest.json()["items"]) == 1
    assert rest.json()["next_cursor"] is None
    assert none.json()["items"] == []
    seen = [r["item"]["id"] for r in first.json()["items"] + rest.json()["items"]]
    assert set(seen) == {str(i) for i in ids}


async def test_suggestions_answer_created_without_a_body(
    api: Api, student: Actor
) -> None:
    """LIB-2: `201`, nothing to read back."""
    client = await api(student)

    response = await client.post(
        "/v1/library/suggestions",
        json={"title": "Atom physics", "url": "https://example.org/a", "note": "Good"},
    )

    assert response.status_code == 201
    assert response.content == b""


async def test_report_answers_no_content_and_validates_the_reason(
    api: Api,
    student: Actor,
    other_student: Actor,
    make_draft: MakeDraft,
    set_status: SetStatus,
) -> None:
    """LIB-14: `204`; unknown reasons are `422`."""
    item_id = await make_draft(student)
    await set_status(item_id, ItemStatus.PUBLISHED)
    client = await api(other_student)

    ok = await client.post(
        f"/v1/library/items/{item_id}/report", json={"reason": "wrong_content"}
    )
    bad = await client.post(
        f"/v1/library/items/{item_id}/report", json={"reason": "boring"}
    )
    long = await client.post(
        f"/v1/library/items/{item_id}/report",
        json={"reason": "spam", "text": "x" * 501},
    )

    assert ok.status_code == 204
    assert bad.status_code == 422
    assert long.status_code == 422


# - - - Auth and IDOR - - -

PROTECTED = [
    ("POST", "/v1/library/materials"),
    ("POST", "/v1/library/materials/{id}/files"),
    ("POST", "/v1/library/materials/{id}/submit"),
    ("POST", "/v1/library/materials/{id}/versions"),
    ("PATCH", "/v1/library/materials/{id}"),
    ("DELETE", "/v1/library/materials/{id}"),
    ("GET", "/v1/me/library/uploads"),
    ("POST", "/v1/library/suggestions"),
    ("POST", "/v1/library/items/{id}/report"),
]


@pytest.mark.parametrize(("method", "path"), PROTECTED)
async def test_every_upload_endpoint_needs_a_token(
    api: Api, method: str, path: str
) -> None:
    """LIB-13: `401` without credentials."""
    client = await api(None)

    response = await client.request(
        method, path.format(id="0194a8f0-0000-7000-8000-000000000000"), json={}
    )

    assert response.status_code == 401


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("POST", "/v1/library/materials/{id}/files", {"file_ids": ["{file}"]}),
        ("POST", "/v1/library/materials/{id}/submit", None),
        ("PATCH", "/v1/library/materials/{id}", {"title": "Mine"}),
        ("DELETE", "/v1/library/materials/{id}", None),
    ],
)
async def test_somebody_elses_material_is_a_404_problem(
    api: Api,
    student: Actor,
    other_student: Actor,
    make_draft: MakeDraft,
    files_api: MaterialFilesApi,
    method: str,
    path: str,
    body: dict[str, Any] | None,
) -> None:
    """LIB-13: IDOR: `404 library/not-found`, never `403`."""
    item_id = await make_draft(student)
    file_id = files_api.upload(other_student.user_id)
    client = await api(other_student)
    json = (
        {k: [str(file_id)] if isinstance(v, list) else v for k, v in body.items()}
        if body
        else None
    )

    response = await client.request(method, path.format(id=item_id), json=json)

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["type"] == "library/not-found"


async def test_submit_without_the_attestation_is_a_problem_until_patched(
    api: Api, student: Actor, physics: UUID, files_api: MaterialFilesApi
) -> None:
    """LIB-13: a draft saves with `attested: false`; submit asks for the tick."""
    client = await api(student)
    created = await client.post(
        "/v1/library/materials", json=payload(physics, attested=False)
    )
    item_id = created.json()["id"]
    pdf = files_api.upload(student.user_id)
    await client.post(
        f"/v1/library/materials/{item_id}/files", json={"file_ids": [str(pdf)]}
    )

    refused = await client.post(f"/v1/library/materials/{item_id}/submit")
    patched = await client.patch(
        f"/v1/library/materials/{item_id}", json={"attested": True}
    )
    accepted = await client.post(f"/v1/library/materials/{item_id}/submit")

    assert created.status_code == 201
    assert refused.status_code == 422
    assert refused.json()["type"] == "library/attestation-required"
    assert refused.json()["message_key"] == "library-attestation-required"
    assert patched.status_code == 200
    assert accepted.status_code == 202


async def test_a_ban_answers_forbidden_with_the_end_date(
    api: Api,
    student: Actor,
    physics: UUID,
    uow_factory: UowFactory,
) -> None:
    """LIB-14: `403 library/banned` with `params.until`."""
    until = dt.datetime(2026, 10, 20, tzinfo=dt.UTC)
    async with uow_factory() as uow:
        await uow.moderation.add_sanction(
            Sanction(
                id=new_id(),
                user_id=student.user_id,
                kind=SanctionKind.UPLOAD_BAN,
                reason="x",
                set_by=new_id(),
                created_at=dt.datetime(2026, 10, 1, tzinfo=dt.UTC),
                until=until,
            )
        )
        await uow.commit()
    client = await api(student)

    response = await client.post("/v1/library/materials", json=payload(physics))

    assert response.status_code == 403
    assert response.json()["type"] == "library/banned"
    assert response.json()["params"] == {"until": until.isoformat()}


async def test_body_validation_errors_are_422(
    api: Api, student: Actor, physics: UUID
) -> None:
    """LIB-13: unknown type, empty title, too many years."""
    client = await api(student)

    for changes in (
        {"type": "pamphlet"},
        {"title": ""},
        {"years_of_study": [0]},
        {"language": "klingon"},
    ):
        response = await client.post(
            "/v1/library/materials", json=payload(physics, **changes)
        )
        assert response.status_code == 422, changes


async def test_status_reason_codes_are_published_in_the_openapi_schema(
    api: Api, student: Actor
) -> None:
    """LIB-13: clients translate the system codes of `UploadRow.reason`."""
    client = await api(student)

    schema = (await client.get("/openapi.json")).json()

    codes = schema["components"]["schemas"]["StatusReasonCode"]["enum"]
    assert {"withdrawn_by_owner", "reported", "superseded", "account_closed"} <= set(
        codes
    )
