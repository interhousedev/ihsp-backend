"""Which stored files may be attached to an excuse or its thread."""

from collections.abc import Sequence
from uuid import UUID

from app.modules.academic.domain.excuses.errors import ExcuseAttachmentError
from app.shared.contracts.files import FileRef

MAX_ATTACHMENTS = 5
READY = "ready"
# An explicit allowlist: a prefix such as "text/" would also admit active content.
ALLOWED_TYPES = frozenset(
    {
        "image/png",
        "image/jpeg",
        "image/webp",
        "application/pdf",
        "application/msword",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    }
)


def allowed_type(content_type: str) -> bool:
    """True for photos, PDF and Word documents only."""
    return content_type.lower().split(";")[0].strip() in ALLOWED_TYPES


def check_attachments(
    file_ids: Sequence[UUID], found: dict[UUID, FileRef], owner_id: UUID
) -> None:
    """Every file exists, is the author's, is ready and of an allowed type.

    Raises:
        ExcuseAttachmentError: The first file that breaks a rule.
    """
    if len(file_ids) > MAX_ATTACHMENTS or len(set(file_ids)) != len(file_ids):
        raise ExcuseAttachmentError(params={"reason": "count", "max": MAX_ATTACHMENTS})
    for file_id in file_ids:
        ref = found.get(file_id)
        reason = _problem(ref, owner_id)
        if reason is not None:
            raise ExcuseAttachmentError(
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
