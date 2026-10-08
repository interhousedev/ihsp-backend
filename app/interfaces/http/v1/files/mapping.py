"""Maps use case results to response models."""

from collections.abc import Sequence

from app.interfaces.http.v1.files.schemas import (
    FileItem,
    UploadInfo,
    UploadResponse,
    UsedByItem,
)
from app.modules.files.application.file_views import FileView
from app.modules.files.application.request_upload import UploadTicket
from app.modules.files.domain.used_by import UsedBy


def to_used_by(items: Sequence[UsedBy]) -> list[UsedByItem]:
    """Map usage entries."""
    return [UsedByItem(kind=i.kind, id=i.id, label=i.label) for i in items]


def to_file_item(view: FileView) -> FileItem:
    """Map a FileView to the FileItem of the API contract."""
    file = view.file
    return FileItem(
        id=file.id,
        name=file.name,
        content_type=file.content_type,
        byte_size=file.byte_size,
        purpose=file.purpose,
        status=file.status,
        reject_reason=file.reject_reason,
        text_bytes=file.text_bytes,
        assistant_ready=view.assistant_ready,
        created_at=file.created_at,
        expires_on=view.expires_on,
        used_by=to_used_by(view.used_by),
    )


def to_upload_response(ticket: UploadTicket) -> UploadResponse:
    """Map an upload ticket."""
    upload = ticket.upload
    return UploadResponse(
        file=to_file_item(ticket.view),
        upload=UploadInfo(url=upload.url, headers=dict(upload.headers)),
    )
