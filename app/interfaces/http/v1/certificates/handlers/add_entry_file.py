"""POST /v1/certificates/me/{entry_id}/files."""

from typing import Annotated
from uuid import UUID

from app.interfaces.http.v1.certificates.deps import ContainerDep, StudentActor
from app.interfaces.http.v1.certificates.schemas import CertificateFileResponse

from fastapi import File, UploadFile


async def add_entry_file(
    entry_id: UUID,
    file: Annotated[UploadFile, File()],
    container: ContainerDep,
    actor: StudentActor,
) -> CertificateFileResponse:
    """Attach an uploaded file (.png .jpg .jpeg .pdf .docx) to the caller's entry."""
    data = await file.read()
    stored = await container.certificates.add_entry_file.execute(
        actor.user_id, entry_id, name=file.filename or "certificate", data=data
    )
    return CertificateFileResponse.from_domain(stored)
