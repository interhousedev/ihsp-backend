"""LIB-3, LIB-11: the librarian's book endpoints: auth, shapes, errors."""

from collections.abc import Awaitable, Callable
from uuid import UUID

from app.modules.library.domain.enums import TextStatus
from app.modules.library.wiring import LibraryServices
from app.shared.actor import Actor
from app.shared.contracts.files import FilePurpose, FileScope
from app.shared.ids import new_id
from tests.fakes.library.academic import FakeAcademicDirectory
from tests.fakes.library.files import FakeFilesApi

import pytest
from httpx import AsyncClient

Api = Callable[..., Awaitable[AsyncClient]]


def _body(subject_id: UUID, **changes: object) -> dict[str, object]:
    body: dict[str, object] = {
        "title": "Physics 10",
        "subtitle": None,
        "authors": ["A. Author"],
        "translators": [],
        "language": "uz_latn",
        "year_published": 2022,
        "publisher": None,
        "isbn": None,
        "type": "textbook",
        "description": "A textbook",
        "years_of_study": [1],
        "subjects": [{"subject_id": str(subject_id), "role": "textbook"}],
        "topics": [],
        "rights": "official",
        "licence": None,
        "rights_basis": {"reference": "Order 12/2024"},
        "rights_proof_file_id": None,
        "cover_file_id": None,
        "visibility": "lyceum",
        "download_allowed": False,
    }
    return {**body, **changes}


@pytest.fixture
def subject(academic: FakeAcademicDirectory) -> UUID:
    """A registered subject."""
    return academic.add_subject(new_id(), "Physics")


async def _create(client: AsyncClient, subject: UUID, **changes: object) -> str:
    response = await client.post(
        "/v1/manage/library/books", json=_body(subject, **changes)
    )
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


# - - - Auth - - -


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/v1/manage/library/books"),
        ("POST", "/v1/manage/library/books"),
        ("GET", f"/v1/manage/library/books/{new_id()}"),
        ("PATCH", f"/v1/manage/library/books/{new_id()}"),
        ("POST", f"/v1/manage/library/books/{new_id()}/publish"),
        ("POST", f"/v1/manage/library/books/{new_id()}/unpublish"),
        ("POST", f"/v1/manage/library/books/{new_id()}/takedown"),
        ("POST", f"/v1/manage/library/books/{new_id()}/files"),
        ("POST", "/v1/manage/library/import"),
    ],
)
async def test_every_manage_endpoint_needs_a_librarian(
    api: Api, student: Actor, teacher: Actor, method: str, path: str
) -> None:
    """LIB-11: 401 for visitors, 403 for students and teachers."""
    anonymous = await api(None)
    as_student = await api(student)
    as_teacher = await api(teacher)

    assert (await anonymous.request(method, path, json={})).status_code == 401
    assert (await as_student.request(method, path, json={})).status_code == 403
    assert (await as_teacher.request(method, path, json={})).status_code == 403


# - - - Happy path and shapes - - -


async def test_create_edit_publish_and_take_down_over_http(
    api: Api,
    library: LibraryServices,
    librarian: Actor,
    student: Actor,
    subject: UUID,
    files_api: FakeFilesApi,
) -> None:
    """LIB-3: the whole life of a book through the endpoints."""
    client = await api(librarian)
    book_id = await _create(client, subject)
    file_id = files_api.add_file(
        owner_id=librarian.user_id,
        scope=FileScope.LIBRARY,
        purpose=FilePurpose.LIBRARY_BOOK,
    )

    attached = await client.post(
        f"/v1/manage/library/books/{book_id}/files",
        json={"file_id": str(file_id), "format": "pdf", "is_primary": True},
    )
    async with library.core.uow_factory() as uow:
        item = await uow.items.get(UUID(book_id))
        assert item is not None and item.primary_file is not None
        item.primary_file.text_status = TextStatus.READY
        await uow.items.save_file(item.primary_file)
        await uow.commit()
    patched = await client.patch(
        f"/v1/manage/library/books/{book_id}", json={"publisher": "Sharq"}
    )
    published = await client.post(f"/v1/manage/library/books/{book_id}/publish")
    as_student = await api(student)
    visible = await as_student.get(f"/v1/library/items/{book_id}")
    taken = await client.post(
        f"/v1/manage/library/books/{book_id}/takedown", json={"reason": "copyright"}
    )
    hidden = await as_student.get(f"/v1/library/items/{book_id}")

    assert attached.status_code == 201
    assert attached.json()["is_primary"] is True
    assert attached.json()["text_status"] == "pending"
    assert patched.json()["publisher"] == "Sharq"
    assert published.json()["status"] == "published"
    assert visible.status_code == 200
    assert taken.json()["status"] == "unpublished"
    assert taken.json()["status_reason"] == "takedown"
    assert hidden.status_code == 404


async def test_draft_endpoint_returns_item_input_and_checklist(
    api: Api, librarian: Actor, subject: UUID
) -> None:
    """LIB-3: `BookDraft` = `{item, input, checklist}` with the saved form."""
    client = await api(librarian)
    book_id = await _create(client, subject)

    response = await client.get(f"/v1/manage/library/books/{book_id}")

    body = response.json()
    assert set(body) == {"item", "input", "checklist"}
    assert body["item"]["status"] == "draft" and body["item"]["kind"] == "book"
    assert body["input"]["title"] == "Physics 10"
    assert body["input"]["subjects"] == [
        {"subject_id": str(subject), "role": "textbook", "year_of_study": None}
    ]
    assert body["input"]["rights_basis"]["reference"] == "Order 12/2024"
    assert body["checklist"] == [
        {"key": "rights", "ok": True},
        {"key": "text_status", "ok": False},
        {"key": "cover", "ok": False},
        {"key": "subjects", "ok": True},
    ]


async def test_book_table_rows(api: Api, librarian: Actor, subject: UUID) -> None:
    """LIB-3: `BookRow` = item card, status, visibility, rights, text status."""
    client = await api(librarian)
    await _create(client, subject)

    body = (await client.get("/v1/manage/library/books?status=draft")).json()

    (row,) = body["items"]
    assert set(row) == {
        "item", "status", "visibility", "rights", "text_status", "updated_at",
    }  # fmt: skip
    assert row["status"] == "draft" and row["rights"] == "official"
    assert row["text_status"] == "none" and row["item"]["title"] == "Physics 10"
    assert (await client.get("/v1/manage/library/books?status=published")).json()[
        "items"
    ] == []


# - - - Errors - - -


async def test_publishing_an_incomplete_book_is_a_422_with_the_missing_fields(
    api: Api, librarian: Actor, subject: UUID
) -> None:
    """LIB-3: `library/rights-incomplete` with `params.missing[]`."""
    client = await api(librarian)
    book_id = await _create(client, subject, rights_basis={})

    response = await client.post(f"/v1/manage/library/books/{book_id}/publish")

    assert response.status_code == 422
    assert response.json()["type"] == "library/rights-incomplete"
    assert response.json()["params"]["missing"] == [
        "rights_basis.reference",
        "text_status",
        "cover",
    ]


async def test_public_visibility_with_official_rights_is_a_422(
    api: Api, librarian: Actor, subject: UUID
) -> None:
    """LIB-3: `library/visibility-conflict`."""
    client = await api(librarian)

    response = await client.post(
        "/v1/manage/library/books", json=_body(subject, visibility="public")
    )

    assert response.status_code == 422
    assert response.json()["type"] == "library/visibility-conflict"


async def test_takedown_without_a_reason_is_a_422_and_publish_twice_a_409(
    api: Api, librarian: Actor, subject: UUID
) -> None:
    """LIB-3: `library/reason-required`; unpublishing a draft is `not-editable`."""
    client = await api(librarian)
    book_id = await _create(client, subject)

    no_reason = await client.post(f"/v1/manage/library/books/{book_id}/takedown")
    draft_unpublish = await client.post(f"/v1/manage/library/books/{book_id}/unpublish")

    assert (no_reason.status_code, no_reason.json()["type"]) == (
        422,
        "library/reason-required",
    )
    assert (draft_unpublish.status_code, draft_unpublish.json()["type"]) == (
        409,
        "library/not-editable",
    )


@pytest.mark.parametrize("field", ["title", "authors", "rights", "visibility"])
async def test_patch_refuses_null_for_required_fields(
    api: Api, librarian: Actor, subject: UUID, field: str
) -> None:
    """LIB-3: only nullable fields may be cleared."""
    client = await api(librarian)
    book_id = await _create(client, subject)

    response = await client.patch(
        f"/v1/manage/library/books/{book_id}", json={field: None}
    )

    assert response.status_code == 422


async def test_patch_can_clear_a_nullable_field(
    api: Api, librarian: Actor, subject: UUID
) -> None:
    """LIB-3: `publisher: null` clears it; absent keys change nothing."""
    client = await api(librarian)
    book_id = await _create(client, subject, publisher="Sharq")

    response = await client.patch(
        f"/v1/manage/library/books/{book_id}", json={"publisher": None}
    )

    assert response.json()["publisher"] is None
    assert response.json()["title"] == "Physics 10"


async def test_unknown_book_and_unknown_subject_are_handled(
    api: Api, librarian: Actor, subject: UUID
) -> None:
    """LIB-3: 404 for an unknown book, 422 for an unknown subject."""
    client = await api(librarian)

    missing = await client.get(f"/v1/manage/library/books/{new_id()}")
    bad_subject = await client.post("/v1/manage/library/books", json=_body(new_id()))
    unknown_action = await client.post(f"/v1/manage/library/books/{new_id()}/explode")

    assert missing.status_code == 404
    assert bad_subject.status_code == 422
    assert bad_subject.json()["type"] == "library/invalid-reference"
    assert unknown_action.status_code == 404


async def test_a_file_of_another_user_cannot_be_attached(
    api: Api,
    librarian: Actor,
    other_student: Actor,
    subject: UUID,
    files_api: FakeFilesApi,
) -> None:
    """LIB-3: `library/file-invalid` (422)."""
    client = await api(librarian)
    book_id = await _create(client, subject)
    foreign = files_api.add_file(
        owner_id=other_student.user_id,
        scope=FileScope.LIBRARY,
        purpose=FilePurpose.LIBRARY_BOOK,
    )

    response = await client.post(
        f"/v1/manage/library/books/{book_id}/files",
        json={"file_id": str(foreign), "format": "pdf", "is_primary": True},
    )

    assert response.status_code == 422
    assert response.json()["type"] == "library/file-invalid"


async def test_import_over_http(
    api: Api,
    librarian: Actor,
    academic: FakeAcademicDirectory,
    files_api: FakeFilesApi,
) -> None:
    """LIB-3: `{created, errors: [{row, message}]}`."""
    academic.add_subject(new_id(), "Physics")
    csv_file = files_api.add_file(
        owner_id=librarian.user_id,
        name="books.csv",
        scope=FileScope.LIBRARY,
        purpose=FilePurpose.LIBRARY_BOOK,
        data=(
            "title,rights,reference,subjects\n"
            "Kitob,official,Order 1,Physics\n"
            ",official,Order 2,Physics\n"
        ).encode(),
    )
    client = await api(librarian)

    response = await client.post(
        "/v1/manage/library/import", json={"csv_file_id": str(csv_file)}
    )

    assert response.status_code == 200
    assert response.json() == {
        "created": 1,
        "errors": [{"row": 3, "message": 'Column "title" is empty.'}],
    }
