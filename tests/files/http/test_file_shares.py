"""HTTP: sharing a file by link or with a person; denial and revocation."""

from collections.abc import Callable
from dataclasses import replace
from types import SimpleNamespace
from uuid import UUID

from app.interfaces.http.dependencies import get_actor
from app.interfaces.http.v1.files import ROUTERS
from app.modules.files.domain.status import FileStatus
from app.shared.actor import Actor, Role
from app.shared.contracts.files import FileScope
from tests.conftest import HttpClientFactory
from tests.fakes.ai.contracts import FakeIdentity, make_user
from tests.fakes.files.services import FilesFakes
from tests.files.helpers import make_pdf, sha256_b64

import pytest
from httpx import AsyncClient

PDF = make_pdf("Shared text")


@pytest.fixture
def as_user() -> dict[str, Actor]:
    """Who the next request runs as."""
    return {}


@pytest.fixture
def recipient(make_actor: Callable[..., Actor]) -> Actor:
    """The student the file is shared with."""
    return make_actor(Role.STUDENT)


@pytest.fixture
async def api(
    http_client: HttpClientFactory,
    fakes: FilesFakes,
    as_user: dict[str, Actor],
    student: Actor,
    recipient: Actor,
) -> AsyncClient:
    """A client whose requests run as `as_user["actor"]` (the owner at first)."""
    as_user["actor"] = student
    people = [
        replace(make_user(Role.STUDENT), id=actor.user_id)
        for actor in (student, recipient)
    ]
    client: AsyncClient = await http_client(
        ROUTERS,
        overrides={get_actor: lambda: as_user["actor"]},
        files=fakes.services,
        identity=SimpleNamespace(directory=FakeIdentity(*people)),
    )
    return client


@pytest.fixture
async def file_id(api: AsyncClient, fakes: FilesFakes) -> UUID:
    """A ready file of the owner."""
    response = await api.post(
        "/v1/files",
        json={
            "name": "notes.pdf",
            "size": len(PDF),
            "content_type": "application/pdf",
            "sha256_b64": sha256_b64(PDF),
            "purpose": "ai_upload",
        },
    )
    assert response.status_code == 201
    found = UUID(response.json()["file"]["id"])
    row = fakes.db.row(found)
    fakes.db.store.rows[found] = replace(row, status=FileStatus.READY)
    return found


async def test_a_stranger_cannot_read_a_file_or_its_shares(
    api: AsyncClient, as_user: dict[str, Actor], recipient: Actor, file_id: UUID
) -> None:
    """FILE-SHARE: no grant, 404 everywhere."""
    as_user["actor"] = recipient

    assert (await api.get(f"/v1/files/shared/{file_id}/url")).status_code == 404
    assert (await api.get(f"/v1/files/{file_id}/shares")).status_code == 404
    assert (await api.get(f"/v1/files/{file_id}/url")).status_code == 404
    link = await api.post(f"/v1/files/{file_id}/shares/link")
    assert link.status_code == 404


async def test_a_named_recipient_downloads_until_revoked(
    api: AsyncClient,
    as_user: dict[str, Actor],
    student: Actor,
    recipient: Actor,
    file_id: UUID,
) -> None:
    """FILE-SHARE: a grant opens only the shared route; revoking closes it at once."""
    shared = await api.put(f"/v1/files/{file_id}/shares/{recipient.user_id}")
    as_user["actor"] = recipient

    listed = (await api.get("/v1/me/shared-files")).json()
    url = await api.get(f"/v1/files/shared/{file_id}/url")
    owner_route = await api.get(f"/v1/files/{file_id}")
    rename = await api.patch(f"/v1/files/{file_id}", json={"name": "x.pdf"})
    delete = await api.delete(f"/v1/files/{file_id}")

    assert shared.status_code == 204
    assert [item["id"] for item in listed["items"]] == [str(file_id)]
    assert url.status_code == 200
    assert owner_route.status_code == 404
    assert rename.status_code == 404
    assert delete.status_code == 404

    as_user["actor"] = student
    await api.delete(f"/v1/files/{file_id}/shares/{recipient.user_id}")
    as_user["actor"] = recipient

    assert (await api.get(f"/v1/files/shared/{file_id}/url")).status_code == 404
    assert (await api.get("/v1/me/shared-files")).json()["items"] == []


async def test_a_link_joins_and_turning_it_off_removes_who_joined(
    api: AsyncClient,
    as_user: dict[str, Actor],
    student: Actor,
    recipient: Actor,
    file_id: UUID,
) -> None:
    """FILE-SHARE: a link needs sign-in and stops working when turned off."""
    token = (await api.post(f"/v1/files/{file_id}/shares/link")).json()["token"]
    as_user["actor"] = recipient

    joined = await api.post("/v1/files/shares/join", json={"token": token})
    wrong = await api.post("/v1/files/shares/join", json={"token": "y" * 43})

    assert joined.status_code == 200
    assert joined.json()["id"] == str(file_id)
    assert wrong.status_code == 404

    as_user["actor"] = student
    await api.delete(f"/v1/files/{file_id}/shares/link")
    as_user["actor"] = recipient

    assert (await api.get(f"/v1/files/shared/{file_id}/url")).status_code == 404
    again = await api.post("/v1/files/shares/join", json={"token": token})
    assert again.status_code == 404


async def test_a_revoked_user_cannot_come_back_through_the_link(
    api: AsyncClient,
    as_user: dict[str, Actor],
    student: Actor,
    recipient: Actor,
    file_id: UUID,
) -> None:
    """FILE-SHARE: a person the owner removed stays out."""
    token = (await api.post(f"/v1/files/{file_id}/shares/link")).json()["token"]
    await api.put(f"/v1/files/{file_id}/shares/{recipient.user_id}")
    await api.delete(f"/v1/files/{file_id}/shares/{recipient.user_id}")
    as_user["actor"] = recipient

    response = await api.post("/v1/files/shares/join", json={"token": token})

    assert response.status_code == 404
    assert (await api.get(f"/v1/files/shared/{file_id}/url")).status_code == 404


async def test_a_deleted_file_is_gone_for_the_recipient(
    api: AsyncClient,
    as_user: dict[str, Actor],
    fakes: FilesFakes,
    recipient: Actor,
    file_id: UUID,
) -> None:
    """FILE-SHARE: the grant does not outlive the file."""
    await api.put(f"/v1/files/{file_id}/shares/{recipient.user_id}")
    row = fakes.db.row(file_id)
    fakes.db.store.rows[file_id] = replace(row, status=FileStatus.DELETED)
    as_user["actor"] = recipient

    assert (await api.get(f"/v1/files/shared/{file_id}/url")).status_code == 404
    assert (await api.get("/v1/me/shared-files")).json()["items"] == []


async def test_a_recipient_can_leave(
    api: AsyncClient,
    as_user: dict[str, Actor],
    recipient: Actor,
    file_id: UUID,
) -> None:
    """FILE-SHARE: removing a file from "shared with me" drops the grant."""
    await api.put(f"/v1/files/{file_id}/shares/{recipient.user_id}")
    as_user["actor"] = recipient

    left = await api.delete(f"/v1/files/shared/{file_id}")

    assert left.status_code == 204
    assert (await api.get(f"/v1/files/shared/{file_id}/url")).status_code == 404


async def test_a_managed_file_cannot_be_shared(
    api: AsyncClient, fakes: FilesFakes, file_id: UUID
) -> None:
    """FILE-SHARE: library, course and mail files keep their own access rules."""
    row = fakes.db.row(file_id)
    fakes.db.store.rows[file_id] = replace(row, scope=FileScope.LIBRARY)

    response = await api.post(f"/v1/files/{file_id}/shares/link")

    assert response.status_code == 403


async def test_sharing_with_yourself_is_refused(
    api: AsyncClient, student: Actor, file_id: UUID
) -> None:
    """FILE-SHARE: the owner needs no grant."""
    response = await api.put(f"/v1/files/{file_id}/shares/{student.user_id}")

    assert response.status_code == 422


@pytest.mark.parametrize(
    ("method", "suffix"),
    [
        ("GET", "/shares"),
        ("POST", "/shares/link"),
        ("DELETE", "/shares/link"),
        ("PUT", "/shares/{user}"),
        ("DELETE", "/shares/{user}"),
    ],
)
async def test_a_recipient_cannot_manage_the_shares(
    api: AsyncClient,
    as_user: dict[str, Actor],
    student: Actor,
    recipient: Actor,
    file_id: UUID,
    method: str,
    suffix: str,
) -> None:
    """FILE-SHARE: a grant is for downloading; managing stays the owner's."""
    await api.put(f"/v1/files/{file_id}/shares/{recipient.user_id}")
    as_user["actor"] = recipient
    path = suffix.format(user=student.user_id)

    response = await api.request(method, f"/v1/files/{file_id}{path}")

    assert response.status_code == 404
    assert (await api.get(f"/v1/files/shared/{file_id}/url")).status_code == 200


async def test_turning_the_link_off_keeps_a_person_named_directly(
    api: AsyncClient,
    as_user: dict[str, Actor],
    recipient: Actor,
    file_id: UUID,
) -> None:
    """FILE-SHARE: only people who joined through the link lose access."""
    await api.post(f"/v1/files/{file_id}/shares/link")
    await api.put(f"/v1/files/{file_id}/shares/{recipient.user_id}")

    await api.delete(f"/v1/files/{file_id}/shares/link")
    as_user["actor"] = recipient

    assert (await api.get(f"/v1/files/shared/{file_id}/url")).status_code == 200


async def test_leaving_without_a_grant_is_a_404(
    api: AsyncClient, as_user: dict[str, Actor], recipient: Actor, file_id: UUID
) -> None:
    """FILE-SHARE: leaving reveals nothing about a file the caller cannot open."""
    as_user["actor"] = recipient

    response = await api.delete(f"/v1/files/shared/{file_id}")

    assert response.status_code == 404
