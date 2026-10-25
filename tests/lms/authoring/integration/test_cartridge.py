"""Cartridge import job, export and re-import on the real database."""

import io
import zipfile
from typing import Any
from uuid import UUID

from app.modules.lms.domain.cartridge.errors import CartridgeImportNotFoundError
from app.modules.lms.domain.cartridge.exporter import validate_cartridge
from app.modules.lms.infrastructure.authoring.uow import SqlAuthoringUnitOfWork
from app.modules.lms.infrastructure.cartridge_reports import (
    MemoryCartridgeImportResults,
)
from app.modules.lms.ports.authoring.unit_of_work import AuthoringUnitOfWork
from app.modules.lms.wiring_cartridge import CartridgeServices, assemble_cartridge
from app.shared.actor import Actor, Role
from app.shared.contracts.files import FilePurpose, FileRef, FileScope
from app.shared.db.uow_testing import noop_audit_writer, noop_outbox_writer
from app.shared.jobs import MemoryJobTracker
from tests.fakes.clock import FixedClock
from tests.fakes.lms.files import FakeFilesApi
from tests.fakes.lms.identity import FakeIdentityDirectory
from tests.fakes.tasks import FakeTaskKicker
from tests.lms.cartridge.fixtures import ocw_like, openstax_like

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


class BytesFiles(FakeFilesApi):
    """Fake files that keep their content."""

    def __init__(self) -> None:
        """Start empty."""
        super().__init__()
        self.data: dict[UUID, bytes] = {}
        self.names: dict[UUID, str] = {}
        self.deleted: list[UUID] = []

    async def store_bytes(self, **kwargs: Any) -> FileRef:
        """Keep the bytes."""
        ref = await super().store_bytes(**kwargs)
        self.data[ref.id] = kwargs["data"]
        self.names[ref.id] = kwargs["name"]
        return ref

    async def read_bytes(self, file_id: UUID) -> bytes:
        """Return what was stored."""
        return self.data[file_id]

    async def get_many(self, file_ids: Any) -> dict[UUID, FileRef]:  # noqa: ANN401
        """Return refs with the stored names."""
        found = await super().get_many(file_ids)
        return {
            fid: FileRef(
                id=fid,
                owner_id=ref.owner_id,
                scope=FileScope.STAFF,
                purpose=FilePurpose.LINK,
                name=self.names.get(fid, ref.name),
                content_type="application/octet-stream",
                byte_size=len(self.data.get(fid, b"")),
                status=ref.status,
                text_bytes=None,
            )
            for fid, ref in found.items()
        }

    async def delete_file(self, file_id: UUID) -> None:
        """Remember the deletion."""
        self.deleted.append(file_id)


@pytest.fixture
def bytes_files() -> BytesFiles:
    """Files with content."""
    return BytesFiles()


@pytest.fixture
def cartridge(
    sessionmaker_in_tx: async_sessionmaker[AsyncSession],
    clock: FixedClock,
    identity: FakeIdentityDirectory,
    bytes_files: BytesFiles,
) -> CartridgeServices:
    """Cartridge use cases on SQL inside the test transaction."""

    def uow_factory() -> AuthoringUnitOfWork:
        return SqlAuthoringUnitOfWork(
            sessionmaker_in_tx, noop_outbox_writer, noop_audit_writer
        )

    return assemble_cartridge(
        uow_factory,
        clock=clock,
        identity=identity,
        files=bytes_files,
        kicker=FakeTaskKicker(),
        tracker=MemoryJobTracker(),
        results=MemoryCartridgeImportResults(),
    )


async def _run(
    services: CartridgeServices, actor: Actor, data: bytes
) -> dict[str, Any]:
    job_id = await services.start_import.execute(actor, name="c.imscc", data=data)
    kicker = services.start_import.kicker
    assert isinstance(kicker, FakeTaskKicker)
    _, kwargs = kicker.calls[-1]
    await services.run_import.execute(
        job_id=job_id, file_id=UUID(kwargs["file_id"]), actor=actor
    )
    return await services.get_import.execute(actor, job_id)


async def _steps(
    sessionmaker_in_tx: async_sessionmaker[AsyncSession], course_id: UUID
) -> list[tuple[str, list[dict[str, Any]]]]:
    uow = SqlAuthoringUnitOfWork(
        sessionmaker_in_tx, noop_outbox_writer, noop_audit_writer
    )
    async with uow:
        course = await uow.courses.get(course_id)
        assert course is not None
        out = []
        for section in course.draft_outline["sections"]:
            steps = await uow.steps.get_many([UUID(s) for s in section["steps"]])
            out.append(
                (section["title"], [steps[UUID(s)].draft for s in section["steps"]])
            )
        return out


def _strip(value: Any) -> Any:  # noqa: ANN401
    if isinstance(value, dict):
        return {k: _strip(v) for k, v in value.items() if k != "id"}
    if isinstance(value, list):
        return [_strip(v) for v in value]
    return value


async def test_import_export_reimport(
    cartridge: CartridgeServices,
    admin: Actor,
    bytes_files: BytesFiles,
    sessionmaker_in_tx: async_sessionmaker[AsyncSession],
) -> None:
    status = await _run(cartridge, admin, openstax_like())
    assert status["status"] == "done", status
    assert status["report"]["steps"] == 7
    course_id = UUID(status["course_id"])
    first = await _steps(sessionmaker_in_tx, course_id)
    assert [title for title, _ in first] == ["Chapter 1", "Chapter 2", "Review"]
    assert "/files/" in first[0][1][0]["blocks"][0]["markdown"]
    assert len(bytes_files.deleted) == 1  # the upload

    exported = await cartridge.export.execute(admin, course_id)
    assert exported.filename.endswith(".imscc")
    assert validate_cartridge(exported.data) == []
    again = await _run(cartridge, admin, exported.data)
    assert again["status"] == "done", again
    second = await _steps(sessionmaker_in_tx, UUID(again["course_id"]))
    assert [t for t, _ in second] == [t for t, _ in first]
    # Same content apart from IDs and the (new) file IDs.
    for (_, a), (_, b) in zip(first, second, strict=True):
        assert [s["title"] for s in a] == [s["title"] for s in b]
        assert [len(s["blocks"]) for s in a] == [len(s["blocks"]) for s in b]
    quiz_a = _strip(first[2][1][0]["blocks"][0]["questions"])
    quiz_b = _strip(second[2][1][0]["blocks"][0]["questions"])
    assert [q["type"] for q in quiz_a] == [q["type"] for q in quiz_b]
    assert [q.get("options") for q in quiz_a[1:]] == [
        q.get("options") for q in quiz_b[1:]
    ]


async def test_broken_cartridge_fails_with_reason(
    cartridge: CartridgeServices, admin: Actor
) -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("../evil", "x")
        archive.writestr("imsmanifest.xml", "<manifest/>")
    status = await _run(cartridge, admin, buffer.getvalue())
    assert status["status"] == "failed"
    assert status["error"] == "unsafe-path"


async def test_only_uploader_sees_the_job(
    cartridge: CartridgeServices, admin: Actor, make_actor: Any  # noqa: ANN401
) -> None:
    job_id = await cartridge.start_import.execute(admin, name="c", data=ocw_like())
    other = make_actor(Role.LMS_ADMIN)
    with pytest.raises(CartridgeImportNotFoundError):
        await cartridge.get_import.execute(other, job_id)
    view = await cartridge.get_import.execute(admin, job_id)
    assert view["status"] == "queued"


async def test_copy_course_keeps_structure(
    cartridge: CartridgeServices,
    admin: Actor,
    sessionmaker_in_tx: async_sessionmaker[AsyncSession],
) -> None:
    status = await _run(cartridge, admin, openstax_like())
    course_id = UUID(status["course_id"])
    original = await _steps(sessionmaker_in_tx, course_id)

    copied = await cartridge.copy.execute(admin, course_id)
    assert copied.course_id != course_id
    assert copied.title.endswith(" (copy)")
    uow = SqlAuthoringUnitOfWork(
        sessionmaker_in_tx, noop_outbox_writer, noop_audit_writer
    )
    async with uow:
        course = await uow.courses.get(copied.course_id)
        assert course is not None
        assert course.title == copied.title
        assert course.created_by == admin.user_id
        assert course.live_version_id is None
    copy = await _steps(sessionmaker_in_tx, copied.course_id)
    assert [t for t, _ in copy] == [t for t, _ in original]
    for (_, a), (_, b) in zip(original, copy, strict=True):
        assert [s["title"] for s in a] == [s["title"] for s in b]
        assert [[blk["type"] for blk in s["blocks"]] for s in a] == [
            [blk["type"] for blk in s["blocks"]] for s in b
        ]
