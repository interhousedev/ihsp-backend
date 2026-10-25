"""Fixtures of the catalogue tests: audit capture, a librarian's world."""

from typing import cast

from app.modules.library.domain.entities import SubjectLink
from app.modules.library.domain.enums import SubjectRole
from app.modules.library.infrastructure.uow import LibrarySqlUnitOfWork
from app.modules.library.ports.unit_of_work import LibraryUnitOfWork
from app.modules.library.wiring import LibraryServices, build
from app.modules.library.wiring_core import CoreOverrides
from app.shared.contracts.files import FilesApi
from app.shared.contracts.identity import IdentityDirectory
from app.shared.db.uow_testing import noop_outbox_writer
from app.shared.ids import new_id
from app.shared.notifications import AuditDraft
from app.shared.wiring import ModuleDeps
from tests.fakes.library.academic import FakeAcademicDirectory
from tests.fakes.library.catalogue_files import FakeScanFilesApi
from tests.fakes.library.identity import FakeLibraryIdentity

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@pytest.fixture
def audit_log() -> list[AuditDraft]:
    """Every audit draft written by the units of work of `audited_library`."""
    return []


@pytest.fixture
def audited_library(
    module_deps: ModuleDeps,
    identity: FakeLibraryIdentity,
    files_api: FakeScanFilesApi,
    academic: FakeAcademicDirectory,
    sessionmaker_in_tx: async_sessionmaker[AsyncSession],
    audit_log: list[AuditDraft],
) -> LibraryServices:
    """The module over the fakes with an audit writer that records the drafts."""

    async def record(session: AsyncSession, drafts: list[AuditDraft]) -> None:
        audit_log.extend(drafts)

    def factory() -> LibraryUnitOfWork:
        return LibrarySqlUnitOfWork(sessionmaker_in_tx, noop_outbox_writer, record)

    return build(
        module_deps,
        identity=cast(IdentityDirectory, identity),
        files=cast(FilesApi, files_api),
        academic=academic,
        overrides=CoreOverrides(uow_factory=factory),
    )


@pytest.fixture
def physics(academic: FakeAcademicDirectory) -> SubjectLink:
    """A registered subject as a tag of a book."""
    subject_id = academic.add_subject(new_id(), "Physics")
    return SubjectLink(subject_id, SubjectRole.TEXTBOOK)


@pytest.fixture
def files_api() -> FakeScanFilesApi:
    """Files with outlines and failures (replaces the shared in-memory fake)."""
    return FakeScanFilesApi()
