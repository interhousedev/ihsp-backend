"""HTTP contract of the files area: paths, fields, status codes, error types."""

from collections.abc import Callable
from dataclasses import replace
from datetime import date
from typing import Any
from uuid import UUID, uuid4

from app.interfaces.http.dependencies import get_actor
from app.interfaces.http.v1.files import ROUTERS
from app.modules.files.domain.used_by import UsedBy
from app.modules.files.ports.storage import PresignedUpload
from app.shared.actor import Actor
from tests.conftest import HttpClientFactory
from tests.fakes.clock import FixedClock
from tests.fakes.files.services import DEFAULT_LIMITS, FilesFakes, build_files_fakes
from tests.fakes.tasks import FakeTaskKicker
from tests.files.helpers import PNG_BYTES, make_pdf, sha256_b64

import pytest
from httpx import AsyncClient

PDF = make_pdf("Hello from HTTP")
FILE_ITEM_FIELDS = {
    "id",
    "name",
    "content_type",
    "byte_size",
    "purpose",
    "status",
    "reject_reason",
    "text_bytes",
    "assistant_ready",
    "created_at",
    "expires_on",
    "used_by",
}


async def _client(
    http_client: HttpClientFactory, fakes: FilesFakes, actor: Actor
) -> AsyncClient:
    return await http_client(
        ROUTERS, overrides={get_actor: lambda: actor}, files=fakes.services
    )


def _body(data: bytes = PDF, name: str = "notes.pdf") -> dict[str, object]:
    return {
        "name": name,
        "size": len(data),
        "content_type": "application/pdf",
        "sha256_b64": sha256_b64(data),
        "purpose": "link",
    }


def _browser_put(fakes: FilesFakes, created: dict[str, Any], data: bytes) -> None:
    """Send the bytes the way the browser does, with the returned URL and headers."""
    upload = created["upload"]
    fakes.storage.upload(PresignedUpload(upload["url"], upload["headers"]), data)


async def _create(client: AsyncClient, fakes: FilesFakes, data: bytes = PDF) -> UUID:
    """POST /v1/files, play the browser, POST complete; return the file id."""
    created = (await client.post("/v1/files", json=_body(data))).json()
    _browser_put(fakes, created, data)
    file_id = UUID(created["file"]["id"])
    response = await client.post(f"/v1/files/{file_id}/complete")
    assert response.status_code == 200
    return file_id


async def test_post_files_returns_the_pending_file_and_the_upload_request(
    http_client: HttpClientFactory, fakes: FilesFakes, student: Actor
) -> None:
    """POST /v1/files -> {file: FileItem, upload: {url, method, headers}}."""
    client = await _client(http_client, fakes, student)

    response = await client.post("/v1/files", json=_body())

    assert response.status_code == 201
    body = response.json()
    assert set(body) == {"file", "upload"}
    assert set(body["file"]) == FILE_ITEM_FIELDS
    assert body["file"]["status"] == "pending"
    assert body["file"]["purpose"] == "link"
    assert body["file"]["name"] == "notes.pdf"
    assert body["file"]["byte_size"] == len(PDF)
    assert body["file"]["used_by"] == []
    assert body["upload"]["method"] == "PUT"
    assert body["upload"]["url"].startswith("memory://")
    assert body["upload"]["headers"] == {
        "Content-Type": "application/pdf",
        "x-amz-checksum-sha256": sha256_b64(PDF),
    }


async def test_the_whole_flow_over_http(
    http_client: HttpClientFactory, fakes: FilesFakes, student: Actor
) -> None:
    """Upload, complete, process, read, rename, download URL, list, delete."""
    client = await _client(http_client, fakes, student)
    file_id = await _create(client, fakes)
    await fakes.services.process_file.execute(file_id)

    got = await client.get(f"/v1/files/{file_id}")
    renamed = await client.patch(f"/v1/files/{file_id}", json={"name": "renamed.pdf"})
    url = await client.get(f"/v1/files/{file_id}/url", params={"disposition": "inline"})
    listing = await client.get("/v1/me/files")
    deleted = await client.delete(f"/v1/files/{file_id}")

    assert got.status_code == 200
    assert got.json()["status"] == "ready"
    assert got.json()["text_bytes"] is not None
    assert got.json()["assistant_ready"] is True
    assert renamed.json()["name"] == "renamed.pdf"
    assert set(url.json()) == {"url", "expires_at"}
    assert url.json()["expires_at"].endswith("Z")
    assert fakes.storage.get_urls[-1][2] is True
    assert listing.json()["next_cursor"] is None
    assert [item["id"] for item in listing.json()["items"]] == [str(file_id)]
    assert deleted.status_code == 200
    assert deleted.json() == {"used_by": []}
    assert (await client.get(f"/v1/files/{file_id}")).status_code == 410


async def test_delete_reports_what_used_the_file(
    http_client: HttpClientFactory, fakes: FilesFakes, student: Actor
) -> None:
    """DELETE -> {used_by: UsedBy[]} as of before the deletion."""
    client = await _client(http_client, fakes, student)
    file_id = await _create(client, fakes)
    link_id = uuid4()
    fakes.usage.usage[file_id] = [UsedBy("link", link_id, "s.ihsu.uz/Ab3")]

    response = await client.delete(f"/v1/files/{file_id}")

    assert response.json() == {
        "used_by": [{"kind": "link", "id": str(link_id), "label": "s.ihsu.uz/Ab3"}]
    }


async def test_quota_exceeded_is_413_problem_json(
    http_client: HttpClientFactory,
    clock: FixedClock,
    kicker: FakeTaskKicker,
    student: Actor,
) -> None:
    """Error type ``files/quota-exceeded`` with status 413."""
    limits = replace(DEFAULT_LIMITS, student_quota_bytes=len(PDF) - 1)
    fakes = build_files_fakes(clock, kicker, limits=limits)
    client = await _client(http_client, fakes, student)

    response = await client.post("/v1/files", json=_body())

    assert response.status_code == 413
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["type"] == "files/quota-exceeded"
    assert response.json()["message_key"] == "files-quota-exceeded"


@pytest.mark.parametrize(
    ("name", "content_type", "size", "error_type", "status"),
    [
        ("virus.exe", "application/x-msdownload", 10, "files/type-not-allowed", 415),
        ("a.pdf", "application/pdf", 100 * 1024 * 1024 + 1, "files/too-large", 413),
    ],
)
async def test_validation_errors_have_stable_types(
    http_client: HttpClientFactory,
    fakes: FilesFakes,
    student: Actor,
    name: str,
    content_type: str,
    size: int,
    error_type: str,
    status: int,
) -> None:
    """The web translates these ``type`` values."""
    client = await _client(http_client, fakes, student)
    body = {**_body(), "name": name, "content_type": content_type, "size": size}

    response = await client.post("/v1/files", json=body)

    assert response.status_code == status
    assert response.json()["type"] == error_type


async def test_ai_purpose_is_accepted_and_mail_is_not_a_valid_purpose(
    http_client: HttpClientFactory, fakes: FilesFakes, student: Actor
) -> None:
    """purpose: ``ai_upload`` or ``link`` only."""
    client = await _client(http_client, fakes, student)

    ok = await client.post("/v1/files", json={**_body(), "purpose": "ai_upload"})
    bad = await client.post("/v1/files", json={**_body(), "purpose": "mail"})

    assert ok.status_code == 201
    assert ok.json()["file"]["purpose"] == "ai_upload"
    assert bad.status_code == 422
    assert bad.json()["type"] == "common/request-validation"


async def test_complete_without_an_upload_is_409(
    http_client: HttpClientFactory, fakes: FilesFakes, student: Actor
) -> None:
    """files/upload-missing."""
    client = await _client(http_client, fakes, student)
    created = (await client.post("/v1/files", json=_body())).json()

    response = await client.post(f"/v1/files/{created['file']['id']}/complete")

    assert response.status_code == 409
    assert response.json()["type"] == "files/upload-missing"


async def test_a_type_mismatch_is_reported_as_a_rejected_file(
    http_client: HttpClientFactory, fakes: FilesFakes, student: Actor
) -> None:
    """The response is 200 with ``status: rejected`` and the reason."""
    client = await _client(http_client, fakes, student)
    created = (await client.post("/v1/files", json=_body(PNG_BYTES, "fake.pdf"))).json()
    _browser_put(fakes, created, PNG_BYTES)

    response = await client.post(f"/v1/files/{created['file']['id']}/complete")

    assert response.status_code == 200
    assert response.json()["status"] == "rejected"
    assert response.json()["reject_reason"] == "files/type-mismatch"


async def test_another_users_file_is_404(
    http_client: HttpClientFactory,
    fakes: FilesFakes,
    student: Actor,
    make_actor: Callable[..., Actor],
) -> None:
    """Strangers cannot see, rename or delete a file."""
    owner_client = await _client(http_client, fakes, student)
    file_id = await _create(owner_client, fakes)
    stranger = await _client(http_client, fakes, make_actor(*student.roles))

    assert (await stranger.get(f"/v1/files/{file_id}")).status_code == 404
    assert (await stranger.get(f"/v1/files/{file_id}/url")).status_code == 404
    assert (
        await stranger.patch(f"/v1/files/{file_id}", json={"name": "x.pdf"})
    ).status_code == 404
    assert (await stranger.delete(f"/v1/files/{file_id}")).status_code == 404
    assert (await stranger.post(f"/v1/files/{file_id}/complete")).status_code == 404


async def test_an_administrator_can_read_but_not_change_a_file(
    http_client: HttpClientFactory,
    fakes: FilesFakes,
    student: Actor,
    admin: Actor,
) -> None:
    """GET and URL: owner or admin; PATCH and DELETE: owner only."""
    file_id = await _create(await _client(http_client, fakes, student), fakes)
    client = await _client(http_client, fakes, admin)

    assert (await client.get(f"/v1/files/{file_id}")).status_code == 200
    assert (await client.get(f"/v1/files/{file_id}/url")).status_code == 200
    assert (await client.delete(f"/v1/files/{file_id}")).status_code == 404


async def test_the_files_list_is_paginated_and_filtered(
    http_client: HttpClientFactory, fakes: FilesFakes, student: Actor
) -> None:
    """GET /v1/me/files?purpose&cursor&limit -> Page<FileItem>."""
    client = await _client(http_client, fakes, student)
    for index in range(3):
        fakes.clock.advance(minutes=1)
        data = make_pdf(f"file {index}")
        created = (await client.post("/v1/files", json=_body(data))).json()
        _browser_put(fakes, created, data)
        await client.post(f"/v1/files/{created['file']['id']}/complete")

    first = (await client.get("/v1/me/files", params={"limit": 2})).json()
    second = (
        await client.get(
            "/v1/me/files", params={"limit": 2, "cursor": first["next_cursor"]}
        )
    ).json()
    none = (await client.get("/v1/me/files", params={"purpose": "ai_upload"})).json()

    assert len(first["items"]) == 2 and first["next_cursor"]
    assert len(second["items"]) == 1 and second["next_cursor"] is None
    assert none == {"items": [], "next_cursor": None}
    assert (await client.get("/v1/me/files", params={"limit": 101})).status_code == 422


async def test_storage_endpoint_returns_the_quota_bar_fields(
    http_client: HttpClientFactory, fakes: FilesFakes, student: Actor
) -> None:
    """GET /v1/me/storage -> {used_bytes, quota_bytes, term_id, expires_on}."""
    term = uuid4()
    fakes.terms.current = term
    fakes.terms.ends[term] = date(2027, 1, 15)
    client = await _client(http_client, fakes, student)
    await _create(client, fakes)

    response = await client.get("/v1/me/storage")

    assert response.status_code == 200
    assert response.json() == {
        "used_bytes": len(PDF),
        "quota_bytes": DEFAULT_LIMITS.student_quota_bytes,
        "term_id": str(term),
        "expires_on": "2027-01-29",
    }


async def test_requests_without_a_token_are_401(
    http_client: HttpClientFactory, fakes: FilesFakes
) -> None:
    """Every endpoint needs a bearer token."""
    client = await http_client(ROUTERS, files=fakes.services)

    for method, path in [
        ("POST", "/v1/files"),
        ("GET", f"/v1/files/{uuid4()}"),
        ("GET", "/v1/me/files"),
        ("GET", "/v1/me/storage"),
    ]:
        response = await client.request(method, path)
        assert response.status_code == 401, (method, path)


async def test_an_unknown_disposition_is_a_validation_error(
    http_client: HttpClientFactory, fakes: FilesFakes, student: Actor
) -> None:
    """``?disposition=`` is ``inline`` or ``attachment``."""
    client = await _client(http_client, fakes, student)
    file_id = await _create(client, fakes)

    response = await client.get(
        f"/v1/files/{file_id}/url", params={"disposition": "download"}
    )

    assert response.status_code == 422
