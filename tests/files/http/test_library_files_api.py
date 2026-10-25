"""LIB-3, LIB-5 (files part): library files over HTTP."""

from dataclasses import replace
from uuid import UUID

from app.interfaces.http.dependencies import get_actor
from app.interfaces.http.v1.files import ROUTERS
from app.modules.files.ports.storage import PresignedUpload
from app.shared.actor import Actor
from tests.conftest import HttpClientFactory
from tests.fakes.clock import FixedClock
from tests.fakes.files.services import DEFAULT_LIMITS, FilesFakes, build_files_fakes
from tests.fakes.tasks import FakeTaskKicker
from tests.files.helpers import make_pdf, sha256_b64

import pytest
from httpx import AsyncClient

PDF = make_pdf("A library file")


async def _client(
    http_client: HttpClientFactory, fakes: FilesFakes, actor: Actor
) -> AsyncClient:
    return await http_client(
        ROUTERS, overrides={get_actor: lambda: actor}, files=fakes.services
    )


def _body(purpose: str, name: str = "book.pdf") -> dict[str, object]:
    return {
        "name": name,
        "size": len(PDF),
        "content_type": "application/pdf",
        "sha256_b64": sha256_b64(PDF),
        "purpose": purpose,
    }


async def _upload(client: AsyncClient, fakes: FilesFakes, purpose: str) -> UUID:
    """POST /v1/files, play the browser, POST complete; return the file id."""
    created = (await client.post("/v1/files", json=_body(purpose))).json()
    upload = created["upload"]
    fakes.storage.upload(PresignedUpload(upload["url"], upload["headers"]), PDF)
    file_id = UUID(created["file"]["id"])
    assert (await client.post(f"/v1/files/{file_id}/complete")).status_code == 200
    return file_id


@pytest.mark.parametrize("purpose", ["library_book", "library_cover"])
async def test_a_librarian_requests_an_upload_for_books_and_covers(
    http_client: HttpClientFactory, fakes: FilesFakes, librarian: Actor, purpose: str
) -> None:
    """The presign flow accepts the library purposes."""
    client = await _client(http_client, fakes, librarian)

    response = await client.post("/v1/files", json=_body(purpose))

    assert response.status_code == 201
    assert response.json()["file"]["purpose"] == purpose
    assert response.json()["upload"]["url"].startswith("memory://")


async def test_a_student_gets_403_for_a_book_and_201_for_a_material(
    http_client: HttpClientFactory, fakes: FilesFakes, student: Actor
) -> None:
    """Books are for librarians; materials are for everybody."""
    client = await _client(http_client, fakes, student)

    book = await client.post("/v1/files", json=_body("library_book"))
    material = await client.post("/v1/files", json=_body("library_material"))

    assert book.status_code == 403
    assert book.json()["type"] == "common/forbidden"
    assert material.status_code == 201


async def test_an_epub_can_be_requested(
    http_client: HttpClientFactory, fakes: FilesFakes, librarian: Actor
) -> None:
    """`.epub` with `application/epub+zip`."""
    client = await _client(http_client, fakes, librarian)
    body = {
        **_body("library_book", "novel.epub"),
        "content_type": "application/epub+zip",
    }

    response = await client.post("/v1/files", json=body)

    assert response.status_code == 201
    assert response.json()["file"]["content_type"] == "application/epub+zip"


async def test_the_size_error_names_the_limit_of_the_library_scope(
    http_client: HttpClientFactory,
    clock: FixedClock,
    kicker: FakeTaskKicker,
    librarian: Actor,
) -> None:
    """413 `files/too-large` with the ceiling in megabytes for the message."""
    limits = replace(DEFAULT_LIMITS, library_file_max_bytes=300 * 1024 * 1024)
    fakes = build_files_fakes(clock, kicker, limits=limits)
    client = await _client(http_client, fakes, librarian)
    body = {**_body("library_book"), "size": 300 * 1024 * 1024 + 1}

    response = await client.post("/v1/files", json=body)

    assert response.status_code == 413
    assert response.json()["type"] == "files/too-large"
    assert response.json()["params"]["max_mb"] == 300


async def test_generic_endpoints_hide_library_files_from_other_users(
    http_client: HttpClientFactory,
    fakes: FilesFakes,
    student: Actor,
    teacher: Actor,
    librarian: Actor,
    admin: Actor,
) -> None:
    """`GET /v1/files/{id}/url`: 404 to all but the owner, librarians, admins."""
    owner = await _client(http_client, fakes, student)
    file_id = await _upload(owner, fakes, "library_material")

    owner_url = await owner.get(f"/v1/files/{file_id}/url")
    outcomes = {}
    for name, actor in {
        "teacher": teacher,
        "librarian": librarian,
        "admin": admin,
    }.items():
        client = await _client(http_client, fakes, actor)
        outcomes[name] = (
            (await client.get(f"/v1/files/{file_id}/url")).status_code,
            (await client.get(f"/v1/files/{file_id}")).status_code,
        )

    assert owner_url.status_code == 200
    assert outcomes == {
        "teacher": (404, 404),
        "librarian": (200, 200),
        "admin": (200, 200),
    }


async def test_owners_cannot_rename_or_delete_library_files_here(
    http_client: HttpClientFactory, fakes: FilesFakes, student: Actor
) -> None:
    """The library module manages them; My files operations answer 403."""
    client = await _client(http_client, fakes, student)
    file_id = await _upload(client, fakes, "library_material")

    renamed = await client.patch(f"/v1/files/{file_id}", json={"name": "x.pdf"})
    deleted = await client.delete(f"/v1/files/{file_id}")

    assert renamed.status_code == 403
    assert deleted.status_code == 403


async def test_library_files_are_not_listed_in_my_files(
    http_client: HttpClientFactory, fakes: FilesFakes, student: Actor
) -> None:
    """`GET /v1/me/files` is for study files."""
    client = await _client(http_client, fakes, student)
    file_id = await _upload(client, fakes, "library_material")
    await fakes.services.process_file.execute(file_id)

    listing = await client.get("/v1/me/files")

    assert listing.json()["items"] == []
