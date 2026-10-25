"""FILE-3, FILE-7: download URLs, bytes, text pages, search and listing for modules."""

from collections.abc import Callable

from app.modules.files.domain.errors import (
    FileDeletedError,
    FileNotReadyError,
    NoTextError,
    StoredFileNotFoundError,
    TextPageNotFoundError,
)
from app.shared.actor import Actor
from app.shared.contracts.files import FilePurpose
from tests.fakes.files.services import FilesFakes
from tests.files.helpers import (
    DOCX_TYPE,
    PDF_TYPE,
    PNG_BYTES,
    make_docx,
    make_pdf,
    sha256_b64,
    upload_ready,
)

import pytest


async def test_pdf_downloads_inline_with_a_60_second_url(
    fakes: FilesFakes, student: Actor
) -> None:
    """FILE-3: PDFs open inline; the URL is valid for 60 seconds."""
    file_id = await upload_ready(
        fakes, student, name="a.pdf", data=make_pdf("x"), content_type=PDF_TYPE
    )

    result = await fakes.services.get_download_url.execute(student, file_id, None)

    key, filename, inline = fakes.storage.get_urls[-1]
    assert (filename, inline) == ("a.pdf", True)
    assert key == fakes.db.row(file_id).key
    assert "expires=60" in result.url
    assert (result.expires_at - fakes.clock.now()).total_seconds() == 60


async def test_an_attachment_is_forced_for_types_that_may_not_open_inline(
    fakes: FilesFakes, student: Actor
) -> None:
    """FILE-3: DOCX is always downloaded, even if inline was asked."""
    file_id = await upload_ready(
        fakes, student, name="a.docx", data=make_docx("x"), content_type=DOCX_TYPE
    )

    await fakes.services.get_download_url.execute(student, file_id, "inline")

    assert fakes.storage.get_urls[-1][2] is False


async def test_an_image_can_be_downloaded_as_attachment_on_request(
    fakes: FilesFakes, student: Actor
) -> None:
    """The disposition query parameter wins for inline-capable types."""
    file_id = await upload_ready(
        fakes, student, name="a.png", data=PNG_BYTES, content_type="image/png"
    )

    await fakes.services.get_download_url.execute(student, file_id, "attachment")

    assert fakes.storage.get_urls[-1][2] is False


async def test_a_stranger_cannot_get_a_download_url_but_an_admin_can(
    fakes: FilesFakes,
    student: Actor,
    admin: Actor,
    make_actor: Callable[..., Actor],
) -> None:
    """Owner or administrator."""
    file_id = await upload_ready(
        fakes, student, name="a.pdf", data=make_pdf("x"), content_type=PDF_TYPE
    )

    with pytest.raises(StoredFileNotFoundError):
        await fakes.services.get_download_url.execute(
            make_actor(*student.roles), file_id, None
        )
    result = await fakes.services.get_download_url.execute(admin, file_id, None)

    assert result.url.startswith("memory://")


async def test_a_deleted_file_is_gone(fakes: FilesFakes, student: Actor) -> None:
    """UF-SYS-07: links to deleted files return 410."""
    file_id = await upload_ready(
        fakes, student, name="a.pdf", data=make_pdf("x"), content_type=PDF_TYPE
    )
    await fakes.services.delete_file.execute(student, file_id)

    with pytest.raises(FileDeletedError) as caught:
        await fakes.services.get_download_url.execute(student, file_id, None)
    with pytest.raises(FileDeletedError):
        await fakes.services.public.download_url(file_id)

    assert caught.value.status == 410


async def test_a_pending_file_cannot_be_downloaded(
    fakes: FilesFakes, student: Actor
) -> None:
    """Only files that passed the upload checks have a URL."""
    ticket = await fakes.services.request_upload.execute(
        student,
        name="a.pdf",
        size=3,
        content_type=PDF_TYPE,
        sha256_b64=sha256_b64(b"abc"),
        purpose=FilePurpose.LINK,
    )

    with pytest.raises(FileNotReadyError):
        await fakes.services.public.download_url(ticket.view.file.id)


async def test_public_download_url_skips_the_actor_check(
    fakes: FilesFakes, student: Actor
) -> None:
    """FilesApi.download_url is for modules that already checked access."""
    file_id = await upload_ready(
        fakes, student, name="a.pdf", data=make_pdf("x"), content_type=PDF_TYPE
    )

    url = await fakes.services.public.download_url(file_id, inline=False)

    assert url.startswith("memory://")
    assert fakes.storage.get_urls[-1][2] is False


async def test_read_bytes_returns_the_content(
    fakes: FilesFakes, student: Actor
) -> None:
    """Used by the bot (documents) and mail (forwarding)."""
    data = make_pdf("x")
    file_id = await upload_ready(
        fakes, student, name="a.pdf", data=data, content_type=PDF_TYPE
    )

    assert await fakes.services.public.read_bytes(file_id) == data


async def test_text_is_read_in_pages_of_at_most_8_kb(
    fakes: FilesFakes, student: Actor
) -> None:
    """FILE-7: pages of up to 8 KB, 1-based, with the total page count."""
    text = " ".join(f"word{i:05d}" for i in range(4000))
    file_id = await upload_ready(
        fakes, student, name="big.txt", data=text.encode(), content_type="text/plain"
    )

    first = await fakes.services.public.read_text_page(file_id, 1)
    last = await fakes.services.public.read_text_page(file_id, first.pages)

    assert first.pages > 1
    assert (first.file_id, first.page) == (file_id, 1)
    assert len(first.text.encode()) <= 8192
    assert last.page == first.pages
    pages = [
        (await fakes.services.public.read_text_page(file_id, n)).text
        for n in range(1, first.pages + 1)
    ]
    assert "".join(pages) == text


async def test_a_page_out_of_range_is_not_found(
    fakes: FilesFakes, student: Actor
) -> None:
    """Page 0 and pages past the end raise NotFound."""
    file_id = await upload_ready(
        fakes, student, name="a.txt", data=b"short", content_type="text/plain"
    )

    for page in (0, 2):
        with pytest.raises(TextPageNotFoundError):
            await fakes.services.public.read_text_page(file_id, page)


async def test_a_file_without_text_has_no_pages(
    fakes: FilesFakes, student: Actor
) -> None:
    """Images have no text for the assistant."""
    file_id = await upload_ready(
        fakes, student, name="a.png", data=PNG_BYTES, content_type="image/png"
    )

    with pytest.raises(NoTextError):
        await fakes.services.public.read_text_page(file_id, 1)


async def test_search_finds_a_word_in_a_docx_and_shows_a_snippet(
    fakes: FilesFakes, student: Actor
) -> None:
    """FILE-7: search by extracted text, snippets from the sidecar."""
    data = make_docx("Chapter one", "Photosynthesis turns light into chemical energy.")
    file_id = await upload_ready(
        fakes, student, name="biology.docx", data=data, content_type=DOCX_TYPE
    )
    await upload_ready(
        fakes,
        student,
        name="other.txt",
        data=b"nothing here",
        content_type="text/plain",
    )

    found = await fakes.services.public.search_text(student.user_id, "photosynthesis")

    assert [item["file_id"] for item in found] == [file_id]
    assert found[0]["name"] == "biology.docx"
    assert "Photosynthesis" in found[0]["snippet"]


async def test_search_is_limited_to_the_owners_files(
    fakes: FilesFakes, student: Actor, make_actor: Callable[..., Actor]
) -> None:
    """Nobody searches another user's files."""
    await upload_ready(
        fakes, student, name="a.txt", data=b"secret recipe", content_type="text/plain"
    )

    other = await fakes.services.public.search_text(
        make_actor(*student.roles).user_id, "recipe"
    )

    assert other == []


async def test_a_too_short_query_finds_nothing(
    fakes: FilesFakes, student: Actor
) -> None:
    """Queries under two characters are ignored."""
    await upload_ready(
        fakes, student, name="a.txt", data=b"a b c", content_type="text/plain"
    )

    assert await fakes.services.public.search_text(student.user_id, "a") == []


async def test_deleted_files_are_not_found_by_search(
    fakes: FilesFakes, student: Actor
) -> None:
    """Deleting clears the search vector."""
    file_id = await upload_ready(
        fakes, student, name="a.txt", data=b"unique words", content_type="text/plain"
    )
    await fakes.services.delete_file.execute(student, file_id)

    assert await fakes.services.public.search_text(student.user_id, "unique") == []


async def test_list_owned_returns_ready_files_newest_first(
    fakes: FilesFakes, student: Actor, make_actor: Callable[..., Actor]
) -> None:
    """FilesApi.list_owned: ready, not deleted, newest first, limited."""
    first = await upload_ready(
        fakes, student, name="1.txt", data=b"one", content_type="text/plain"
    )
    fakes.clock.advance(minutes=1)
    second = await upload_ready(
        fakes, student, name="2.txt", data=b"two", content_type="text/plain"
    )
    fakes.clock.advance(minutes=1)
    third = await upload_ready(
        fakes, student, name="3.txt", data=b"three", content_type="text/plain"
    )
    await fakes.services.delete_file.execute(student, second)
    await fakes.services.request_upload.execute(
        student,
        name="pending.txt",
        size=3,
        content_type="text/plain",
        sha256_b64=sha256_b64(b"abc"),
        purpose=FilePurpose.LINK,
    )
    owned = await fakes.services.public.list_owned(student.user_id, limit=10)
    limited = await fakes.services.public.list_owned(student.user_id, limit=1)

    assert [ref.id for ref in owned] == [third, first]
    assert [ref.id for ref in limited] == [third]
    assert all(ref.status == "ready" for ref in owned)
    assert await fakes.services.public.list_owned(make_actor().user_id, limit=5) == []


@pytest.mark.parametrize("query", ["", "   ", "\n\t"])
async def test_an_empty_search_lists_the_newest_ready_files_like_list_owned(
    fakes: FilesFakes, student: Actor, query: str
) -> None:
    """B9 lists files with search_text(owner, '', 50): same rows as list_owned."""
    older = await upload_ready(
        fakes, student, name="older.txt", data=b"one", content_type="text/plain"
    )
    fakes.clock.advance(minutes=1)
    newer = await upload_ready(
        fakes, student, name="newer.png", data=PNG_BYTES, content_type="image/png"
    )
    await fakes.services.request_upload.execute(
        student,
        name="pending.txt",
        size=3,
        content_type="text/plain",
        sha256_b64=sha256_b64(b"abc"),
        purpose=FilePurpose.LINK,
    )

    found = await fakes.services.public.search_text(student.user_id, query, 50)
    owned = await fakes.services.public.list_owned(student.user_id, limit=50)

    assert [item["file_id"] for item in found] == [newer, older]
    assert [item["file_id"] for item in found] == [ref.id for ref in owned]
    assert [item["name"] for item in found] == ["newer.png", "older.txt"]
    assert all(item["snippet"] == "" for item in found)


async def test_an_empty_search_honours_the_limit_and_the_owner(
    fakes: FilesFakes, student: Actor, make_actor: Callable[..., Actor]
) -> None:
    """The limit applies and other users' files are never listed."""
    for index in range(3):
        fakes.clock.advance(minutes=1)
        await upload_ready(
            fakes,
            student,
            name=f"{index}.txt",
            data=b"text",
            content_type="text/plain",
        )

    assert len(await fakes.services.public.search_text(student.user_id, "", 2)) == 2
    assert await fakes.services.public.search_text(make_actor().user_id, "", 50) == []
