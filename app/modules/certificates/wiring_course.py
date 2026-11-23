"""Composition of course certificates (built after the LMS)."""

from app.modules.certificates.application.course_certificates import (
    CourseCertificates,
)
from app.modules.certificates.infrastructure.course_store import (
    SqlCourseCertificatesUnitOfWork,
)
from app.shared.contracts.course_certificates import CourseCertificateFacts
from app.shared.contracts.files import FilesApi
from app.shared.contracts.identity import IdentityDirectory
from app.shared.wiring import ModuleDeps


def build_course_certificates(
    deps: ModuleDeps,
    *,
    facts: CourseCertificateFacts,
    files: FilesApi,
    directory: IdentityDirectory,
) -> CourseCertificates:
    """Return the course certificates service on the SQL store."""

    def uow_factory() -> SqlCourseCertificatesUnitOfWork:
        return SqlCourseCertificatesUnitOfWork(
            deps.sessionmaker,
            deps.outbox_writer,
            deps.audit_writer,
            deps.outbox_committed_hook,
        )

    return CourseCertificates(
        uow_factory,
        facts,
        files,
        directory,
        deps.clock,
        str(deps.settings.urls.lms),
    )
