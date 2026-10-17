"""HTTP: /v1/certificates/* follows the API contract (paths, fields, errors)."""

import io
import zipfile
from typing import Any

from app.interfaces.http.dependencies import get_actor
from app.interfaces.http.v1.certificates import ROUTERS
from app.shared.actor import Actor
from tests.certificates.conftest import CertificatesHarness

import pytest
from httpx import AsyncClient, Response

TYPE_KEYS = {
    "id", "code", "name", "levels", "asks_level", "asks_score", "score_min",
    "score_max", "asks_percent", "asks_subject", "asks_year", "builtin", "position",
}  # fmt: skip
ENTRY_KEYS = {
    "id", "type_id", "level", "score", "percent", "subject", "year", "serial",
    "source", "issued_at", "expires_at", "files", "created_at",
}  # fmt: skip
NAME = {"uz": "Test", "ru": "Тест", "en": "Test"}


class Api:
    """A client whose requests run as ``actor``."""

    def __init__(self, h: CertificatesHarness, client: AsyncClient) -> None:
        """Start as the admin."""
        self.h = h
        self.client = client
        self.actor: Actor = h.admin

    def as_(self, actor: Actor) -> "Api":
        """Switch the caller."""
        self.actor = actor
        return self


@pytest.fixture
async def api(h: CertificatesHarness, http_client: Any) -> Api:
    """A client for the certificates routes; ``api.actor`` decides who calls."""
    holder: dict[str, Api] = {}
    client = await http_client(
        ROUTERS, {get_actor: lambda: holder["api"].actor}, certificates=h.services
    )
    holder["api"] = Api(h, client)
    return holder["api"]


def problem(response: Response, status: int, type_: str) -> None:
    """Assert a problem+json answer."""
    assert response.status_code == status, response.text
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["type"] == type_


async def test_types_are_listed_for_any_signed_in_user(
    h: CertificatesHarness, api: Api
) -> None:
    """GET /types returns the contract fields."""
    await h.add_type("sat", score_min=400, score_max=1600)

    response = await api.as_(h.student_actor(h.ann)).client.get(
        "/v1/certificates/types"
    )

    assert response.status_code == 200
    [item] = response.json()
    assert set(item) == TYPE_KEYS
    assert item["score_max"] == 1600


async def test_admin_creates_edits_and_deletes_a_type(
    h: CertificatesHarness, api: Api
) -> None:
    """POST/PATCH/DELETE /admin/types, 204 on delete."""
    created = await api.client.post(
        "/v1/certificates/admin/types",
        json={"code": "toefl", "name": NAME, "levels": ["80"], "asks_score": True},
    )
    type_id = created.json()["id"]
    patched = await api.client.patch(
        f"/v1/certificates/admin/types/{type_id}", json={"score_max": 120}
    )
    deleted = await api.client.delete(f"/v1/certificates/admin/types/{type_id}")

    assert created.status_code == 200 and created.json()["builtin"] is False
    assert (patched.json()["score_max"], patched.json()["levels"]) == (120, ["80"])
    assert deleted.status_code == 204


async def test_type_administration_is_for_admins_only(
    h: CertificatesHarness, api: Api
) -> None:
    """A student gets 403 on /admin/types."""
    api.as_(h.student_actor(h.ann))

    response = await api.client.post(
        "/v1/certificates/admin/types", json={"code": "x", "name": NAME}
    )

    assert response.status_code == 403


async def test_deleting_builtin_and_used_types_is_a_409_with_a_code(
    h: CertificatesHarness, api: Api
) -> None:
    """certificate_type_builtin and certificate_type_in_use."""
    builtin = await h.add_type("cefr", builtin=True)
    used = await h.add_type("sat")
    await h.add_entry(h.ann, used)

    problem(
        await api.client.delete(f"/v1/certificates/admin/types/{builtin.id}"),
        409,
        "certificate_type_builtin",
    )
    problem(
        await api.client.delete(f"/v1/certificates/admin/types/{used.id}"),
        409,
        "certificate_type_in_use",
    )


async def test_student_entry_crud_with_validation(
    h: CertificatesHarness, api: Api
) -> None:
    """POST /me, 422 on a level outside the type, PATCH, GET, DELETE."""
    kind = await h.add_type("ielts", levels=["6.5", "7.0"])
    me = api.as_(h.student_actor(h.ann)).client

    bad = await me.post(
        "/v1/certificates/me", json={"type_id": str(kind.id), "level": "9"}
    )
    ok = await me.post(
        "/v1/certificates/me",
        json={"type_id": str(kind.id), "level": "6.5", "year": 2026},
    )
    entry_id = ok.json()["id"]
    patched = await me.patch(f"/v1/certificates/me/{entry_id}", json={"level": "7.0"})
    listed = await me.get("/v1/certificates/me")
    deleted = await me.delete(f"/v1/certificates/me/{entry_id}")

    assert bad.status_code == 422
    assert set(ok.json()) == ENTRY_KEYS and ok.json()["source"] == "manual"
    assert patched.json()["level"] == "7.0" and patched.json()["year"] == 2026
    assert [e["id"] for e in listed.json()] == [entry_id]
    assert deleted.status_code == 204


async def test_file_upload_quota_type_and_removal(
    h: CertificatesHarness, api: Api
) -> None:
    """Multipart field 'file': 200, 413 over quota, 415 for a wrong type, 204 delete."""
    kind = await h.add_type("sat")
    entry_id = await h.add_entry(h.ann, kind)
    me = api.as_(h.student_actor(h.ann)).client
    url = f"/v1/certificates/me/{entry_id}/files"

    ok = await me.post(
        url, files={"file": ("scan.pdf", b"%PDF data", "application/pdf")}
    )
    wrong = await me.post(
        url, files={"file": ("a.exe", b"x", "application/x-msdownload")}
    )
    h.files.quota = 5
    big = await me.post(url, files={"file": ("b.pdf", b"123456", "application/pdf")})
    removed = await me.delete(f"{url}/{ok.json()['id']}")

    assert ok.status_code == 200
    assert set(ok.json()) == {"id", "name", "size", "content_type"}
    assert wrong.status_code == 415
    assert big.status_code == 413
    assert removed.status_code == 204


async def test_download_redirects_for_the_group_curator_only(
    h: CertificatesHarness, api: Api
) -> None:
    """307 to the presigned URL for the curator; 403 for another group's curator."""
    kind = await h.add_type("sat")
    file_id = await h.add_file(h.ann, await h.add_entry(h.ann, kind))
    path = f"/v1/certificates/files/{file_id}/download"

    ok = await api.as_(h.curator).client.get(path, follow_redirects=False)
    denied = await api.as_(h.other_curator).client.get(path, follow_redirects=False)

    assert ok.status_code == 307
    assert ok.headers["location"].startswith("https://storage.test/")
    assert denied.status_code == 403


async def test_import_emis_returns_the_counters(
    h: CertificatesHarness, api: Api
) -> None:
    """POST /me/import-emis -> created, updated, files, skipped."""
    await h.add_type("cefr", builtin=True)
    from app.shared.contracts.emis import EmisCertificate

    h.emis.items = [
        EmisCertificate(
            "cefr", "B2", 70, None, None, None, None, "S-1", "https://c.uzbmb.uz/s.pdf"
        )
    ]

    response = await api.as_(h.student_actor(h.ann)).client.post(
        "/v1/certificates/me/import-emis"
    )

    assert response.json() == {"created": 1, "updated": 0, "files": 1, "skipped": 0}


async def test_staff_views_follow_the_scope(h: CertificatesHarness, api: Api) -> None:
    """Entries with the student, stats, ranking, groups; 403 for a foreign group."""
    kind = await h.add_type("cefr", levels=["B2"])
    await h.add_entry(h.ann, kind, level="B2")
    await h.add_entry(h.cid, kind, level="B2")
    staff = api.as_(h.curator).client

    entries = await staff.get("/v1/certificates/staff/entries", params={"limit": 10})
    stats = await staff.get("/v1/certificates/staff/stats")
    ranking = await staff.get("/v1/certificates/staff/ranking")
    groups = await staff.get("/v1/certificates/staff/groups")
    foreign = await staff.get(
        "/v1/certificates/staff/entries", params={"group_id": str(h.group_b)}
    )

    body = entries.json()
    assert body["total"] == 1
    assert set(body["items"][0]) == ENTRY_KEYS | {"student"}
    assert body["items"][0]["student"] == {
        "id": str(h.ann.id), "name": "Ann Alpha", "group_id": str(h.group_a),
        "group_name": "2TN1", "subgroup": "1",
    }  # fmt: skip
    assert stats.json()["types"][0]["groups"][0]["counts"] == {"B2": 1}
    assert ranking.json()["items"] == [
        {
            "student_id": str(h.ann.id),
            "name": "Ann Alpha",
            "group_name": "2TN1",
            "count": 1,
        }
    ]
    assert groups.json() == [
        {"id": str(h.group_a), "name": "2TN1", "subgroups": ["1", "2"]}
    ]
    problem(foreign, 403, "certificate_not_curator")


async def test_students_cannot_use_staff_routes(
    h: CertificatesHarness, api: Api
) -> None:
    """A plain student is rejected."""
    response = await api.as_(h.student_actor(h.ann)).client.get(
        "/v1/certificates/staff/entries"
    )

    assert response.status_code == 403


async def test_export_streams_a_zip_named_group_student_file(
    h: CertificatesHarness, api: Api
) -> None:
    """POST /staff/export with file ids or filters answers application/zip."""
    kind = await h.add_type("sat")
    file_id = await h.add_file(h.ann, await h.add_entry(h.ann, kind), "ielts.pdf")

    by_ids = await api.as_(h.curator).client.post(
        "/v1/certificates/staff/export", json={"file_ids": [str(file_id)]}
    )
    by_filter = await api.client.post(
        "/v1/certificates/staff/export", json={"filters": {"group_id": str(h.group_a)}}
    )
    empty = await api.client.post("/v1/certificates/staff/export", json={"filters": {}})

    assert by_ids.headers["content-type"] == "application/zip"
    for response in (by_ids, by_filter):
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            assert archive.namelist() == ["2TN1-Ann Alpha-ielts.pdf"]
    assert empty.status_code == 200
