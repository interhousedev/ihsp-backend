"""UF-WEB-07 (upload part), UF-WEB-18: the whole flow on real PostgreSQL and S3."""

import hashlib
from collections.abc import AsyncIterator
from datetime import date
from uuid import UUID, uuid4

from app.modules.files.domain.errors import StoredFileNotFoundError
from app.modules.files.domain.status import FileStatus
from app.modules.files.infrastructure.extraction.extractor import FileTextExtractor
from app.modules.files.infrastructure.s3.storage import S3Storage
from app.modules.files.infrastructure.uow import SqlFilesUnitOfWork
from app.modules.files.wiring import FilesServices, assemble
from app.settings import Settings
from app.shared.actor import Actor, Role
from app.shared.contracts.files import FilePurpose, FileScope
from app.shared.db.uow_testing import noop_audit_writer, noop_outbox_writer
from tests.fakes.clock import FixedClock
from tests.fakes.files.resolvers import FakeTermResolver, FakeUsageResolver
from tests.fakes.files.services import DEFAULT_LIMITS
from tests.fakes.files.sniffer import SignatureSniffer
from tests.fakes.tasks import FakeTaskKicker
from tests.files.helpers import (
    DOCX_TYPE,
    EPUB_TYPE,
    PDF_TYPE,
    PNG_BYTES,
    TocItem,
    make_docx,
    make_epub,
    make_jpeg,
    make_pdf,
    make_png,
    sha256_b64,
)

import httpx
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


class Stack:
    """The module over real adapters plus the fakes the test steers."""

    def __init__(
        self,
        services: FilesServices,
        storage: S3Storage,
        terms: FakeTermResolver,
        clock: FixedClock,
        kicker: FakeTaskKicker,
    ) -> None:
        """Keep the parts."""
        self.services = services
        self.storage = storage
        self.terms = terms
        self.clock = clock
        self.kicker = kicker

    async def put(self, ticket_url: str, headers: dict[str, str], data: bytes) -> int:
        """Do the browser's PUT; return the HTTP status."""
        async with httpx.AsyncClient() as client:
            response = await client.put(ticket_url, content=data, headers=headers)
        return response.status_code

    async def upload(
        self, actor: Actor, name: str, data: bytes, content_type: str
    ) -> FilesServices:
        """Request, PUT and complete; return the services for chaining."""
        ticket = await self.services.request_upload.execute(
            actor,
            name=name,
            size=len(data),
            content_type=content_type,
            sha256_b64=sha256_b64(data),
            purpose=FilePurpose.LINK,
        )
        assert await self.put(ticket.upload.url, ticket.upload.headers, data) == 200
        self.last = await self.services.complete_upload.execute(
            actor, ticket.view.file.id
        )
        return self.services


@pytest_asyncio.fixture
async def stack(
    settings: Settings,
    s3_bucket: str,
    sessionmaker_in_tx: async_sessionmaker[AsyncSession],
    clock: FixedClock,
    kicker: FakeTaskKicker,
) -> AsyncIterator[Stack]:
    """Real SQL unit of work (rolled back after the test) and the real S3 adapter."""
    storage = S3Storage(
        endpoint_url=settings.s3.endpoint_url,
        public_endpoint_url=settings.s3.public_endpoint_url,
        region=settings.s3.region,
        access_key=settings.s3.access_key,
        secret_key=settings.s3.secret_key.get_secret_value(),
        bucket=s3_bucket,
    )
    terms = FakeTermResolver()

    def uow_factory() -> SqlFilesUnitOfWork:
        return SqlFilesUnitOfWork(
            sessionmaker_in_tx, noop_outbox_writer, noop_audit_writer
        )

    services = assemble(
        uow_factory=uow_factory,
        clock=clock,
        kicker=kicker,
        storage=storage,
        terms=terms,
        usage=FakeUsageResolver(),
        sniffer=SignatureSniffer(),
        extractor=FileTextExtractor(),
        limits=DEFAULT_LIMITS,
        closers=[],
    )
    try:
        yield Stack(services, storage, terms, clock, kicker)
    finally:
        await storage.close()


def student() -> Actor:
    """A fresh student."""
    return Actor(user_id=uuid4(), roles=frozenset({Role.STUDENT}))


async def test_pdf_upload_through_a_presigned_put_to_a_searchable_ready_file(
    stack: Stack,
) -> None:
    """request -> PUT to S3 -> complete -> process -> search -> download -> delete."""
    actor = student()
    term = uuid4()
    stack.terms.current = term
    stack.terms.ends[term] = date(2027, 1, 15)
    data = make_pdf("Photosynthesis happens in chloroplasts")

    services = await stack.upload(actor, "biology.pdf", data, PDF_TYPE)
    file_id = stack.last.file.id
    assert stack.last.file.status == FileStatus.PROCESSING
    assert stack.kicker.calls == [("files.process", {"file_id": str(file_id)})]
    await services.process_file.execute(file_id)

    view = await services.get_file.execute(actor, file_id)
    assert view.file.status == FileStatus.READY
    assert view.file.text_bytes is not None
    assert view.file.metadata == {"pages": 1, "page_starts": [0]}
    assert str(view.expires_on) == "2027-01-29"
    assert await stack.storage.get(view.file.key) == data
    assert await stack.storage.head(view.file.text_key) is not None
    found = await services.public.search_text(actor.user_id, "chloroplasts")
    assert [item["file_id"] for item in found] == [file_id]
    assert "**chloroplasts**" in found[0]["snippet"]
    page = await services.public.read_text_page(file_id, 1)
    assert "Photosynthesis" in page.text
    usage = await services.storage_usage.execute(actor)
    assert usage.used_bytes == len(data)

    url = await services.get_download_url.execute(actor, file_id, "inline")
    async with httpx.AsyncClient() as client:
        downloaded = await client.get(url.url)
    assert downloaded.status_code == 200
    assert downloaded.content == data
    assert downloaded.headers["content-disposition"].startswith("inline;")

    await services.delete_file.execute(actor, file_id)
    assert await stack.storage.head(view.file.key) is None
    assert await stack.storage.head(view.file.text_key) is None
    assert await services.public.search_text(actor.user_id, "chloroplasts") == []


async def test_docx_text_is_found_by_search(stack: Stack) -> None:
    """FILE-7: search finds a word in a DOCX fixture (real PostgreSQL tsvector)."""
    actor = student()
    data = make_docx(
        "Lesson notes", "Mitochondria produce energy.", table=[["term", "Krebs cycle"]]
    )

    services = await stack.upload(actor, "notes.docx", data, DOCX_TYPE)
    await services.process_file.execute(stack.last.file.id)

    mitochondria = await services.public.search_text(actor.user_id, "mitochondria")
    krebs = await services.public.search_text(actor.user_id, "krebs cycle")
    assert [m["name"] for m in mitochondria] == ["notes.docx"]
    assert [m["name"] for m in krebs] == ["notes.docx"]


async def test_a_png_uploaded_as_pdf_is_rejected_and_its_object_deleted(
    stack: Stack,
) -> None:
    """A real object in S3 is removed at once on type mismatch."""
    actor = student()

    await stack.upload(actor, "fake.pdf", PNG_BYTES, PDF_TYPE)

    assert stack.last.file.status == FileStatus.REJECTED
    assert stack.last.file.reject_reason == "files/type-mismatch"
    assert await stack.storage.head(stack.last.file.key) is None


async def test_the_server_refuses_a_put_with_other_bytes_than_declared(
    stack: Stack,
) -> None:
    """FILE-2: the checksum is enforced by S3 itself."""
    actor = student()
    data = make_pdf("declared")
    ticket = await stack.services.request_upload.execute(
        actor,
        name="a.pdf",
        size=len(data),
        content_type=PDF_TYPE,
        sha256_b64=sha256_b64(data),
        purpose=FilePurpose.LINK,
    )
    other = bytes(len(data))

    status = await stack.put(ticket.upload.url, ticket.upload.headers, other)

    assert status in {400, 403}
    assert await stack.storage.head(ticket.view.file.key) is None


async def test_store_bytes_writes_the_object_and_cleanup_removes_it(
    stack: Stack,
) -> None:
    """Mail attachment with expires_days: object in S3, deleted by the daily job."""
    ref = await stack.services.public.store_bytes(
        owner_id=uuid4(),
        scope=FileScope.MAIL,
        purpose=FilePurpose.MAIL,
        name="invoice.pdf",
        data=b"%PDF-1.4 mail",
        expires_days=30,
    )
    assert await stack.services.public.read_bytes(ref.id) == b"%PDF-1.4 mail"
    stack.clock.advance(days=31)

    deleted = await stack.services.cleanup_expired.execute()

    assert deleted >= 1
    refreshed = await stack.services.public.get(ref.id)
    assert refreshed is not None and refreshed.status == "deleted"


async def _upload_as(
    stack: Stack, actor: Actor, name: str, data: bytes, content_type: str, purpose: str
) -> UUID:
    """Request, PUT to S3, complete and process a file; return its id."""
    ticket = await stack.services.request_upload.execute(
        actor,
        name=name,
        size=len(data),
        content_type=content_type,
        sha256_b64=sha256_b64(data),
        purpose=FilePurpose(purpose),
    )
    assert await stack.put(ticket.upload.url, ticket.upload.headers, data) == 200
    view = await stack.services.complete_upload.execute(actor, ticket.view.file.id)
    await stack.services.process_file.execute(view.file.id)
    return view.file.id


async def test_a_library_epub_is_stored_processed_and_served_to_librarians(
    stack: Stack,
) -> None:
    """LIB-3: library scope, EPUB pages and outline in JSONB, 900 s URL, delete."""
    librarian = Actor(user_id=uuid4(), roles=frozenset({Role.STUDENT, Role.LIBRARIAN}))
    reader = student()
    toc: list[TocItem] = [("One", "ch1.xhtml", []), ("Two", "ch2.xhtml#x", [])]
    data = make_epub(["<p>Evergreen oak</p>", "<p>Birch</p>"], toc=toc)

    file_id = await _upload_as(
        stack, librarian, "trees.epub", data, EPUB_TYPE, "library_book"
    )

    public = stack.services.public
    ref = await public.get(file_id)
    assert ref is not None and ref.scope == FileScope.LIBRARY
    assert ref.content_type == EPUB_TYPE and ref.status == "ready"
    assert await public.page_count(file_id) == 2
    assert [(e.title, e.page) for e in await public.read_outline(file_id)] == [
        ("One", 1),
        ("Two", 2),
    ]
    assert (await public.read_text_with_pages(file_id)).page_starts == (0, 14)
    assert await public.sha256(file_id) == hashlib.sha256(data).hexdigest()
    assert await stack.services.cleanup_expired.execute() == 0

    url = await public.download_url(file_id, ttl_seconds=900)
    assert "X-Amz-Expires=900" in url
    async with httpx.AsyncClient() as client:
        assert (await client.get(url)).content == data
    assert await public.check_access(file_id, librarian)
    assert not await public.check_access(file_id, reader)
    with pytest.raises(StoredFileNotFoundError):
        await stack.services.get_download_url.execute(reader, file_id)

    row = await stack.services.get_file.execute(librarian, file_id)
    await public.delete_file(file_id)
    assert await stack.storage.head(row.file.key) is None
    assert await stack.storage.head(row.file.text_key) is None
    assert await public.get(file_id) is None


async def test_photos_uploaded_to_s3_are_combined_into_one_pdf(stack: Stack) -> None:
    """LIB-5: JPEG and PNG objects read from S3, the PDF written back and scanned."""
    author = student()
    photos = [
        await _upload_as(
            stack, author, "a.jpg", make_jpeg(40, 20), "image/jpeg", "library_material"
        ),
        await _upload_as(
            stack, author, "b.png", make_png(20, 40), "image/png", "library_material"
        ),
    ]

    ref = await stack.services.public.combine_images_to_pdf(
        photos,
        owner_id=author.user_id,
        scope=FileScope.LIBRARY,
        purpose=FilePurpose.LIBRARY_MATERIAL,
        name="Week 3",
    )
    await stack.services.process_file.execute(ref.id)

    assert ref.name == "Week 3.pdf"
    assert await stack.services.public.page_count(ref.id) == 2
    pdf = await stack.services.public.read_bytes(ref.id)
    assert pdf.startswith(b"%PDF-1.4")
