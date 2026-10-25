"""Which stored files may be attached to feedback and responses."""

from uuid import UUID

from app.modules.feedback.domain.errors import FeedbackAttachmentError
from app.modules.feedback.domain.feedback import MAX_ATTACHMENTS
from app.shared.contracts.files import FileRef

# An explicit allowlist: a prefix such as "text/" would also admit types that run or
# render active content (text/html, image/svg+xml), so every type is listed.
ALLOWED_TYPES = frozenset(
    {
        "image/png",
        "image/jpeg",
        "image/webp",
        "image/gif",
        "video/mp4",
        "video/webm",
        "video/quicktime",
        "application/pdf",
        "text/plain",
        "text/csv",
        "application/msword",
        "application/vnd.ms-excel",
        "application/vnd.ms-powerpoint",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    }
)
READY = "ready"


def allowed_type(content_type: str) -> bool:
    """True for the listed types only (images, videos, PDF, Office, plain text, CSV)."""
    return content_type.lower().split(";")[0].strip() in ALLOWED_TYPES


def check_attachments(
    file_ids: list[UUID], found: dict[UUID, FileRef], owner_id: UUID
) -> None:
    """Every file exists, belongs to ``owner_id``, is ready and of an allowed type.

    Raises:
        FeedbackAttachmentError: The first file that breaks a rule.
    """
    if len(file_ids) > MAX_ATTACHMENTS:
        raise FeedbackAttachmentError(
            params={"reason": "too_many", "max": MAX_ATTACHMENTS}
        )
    for file_id in file_ids:
        ref = found.get(file_id)
        reason = _problem(ref, owner_id)
        if reason is not None:
            raise FeedbackAttachmentError(
                params={"file_id": str(file_id), "reason": reason}
            )


def _problem(ref: FileRef | None, owner_id: UUID) -> str | None:
    if ref is None:
        return "not_found"
    if ref.owner_id != owner_id:
        return "not_owner"
    if ref.status != READY:
        return "not_ready"
    if not allowed_type(ref.content_type):
        return "type"
    return None
