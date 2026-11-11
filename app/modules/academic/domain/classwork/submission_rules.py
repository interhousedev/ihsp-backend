"""Pure rules of homework submissions: files, comment, lateness."""

import datetime as dt
from collections.abc import Sequence
from typing import Literal
from uuid import UUID

from app.modules.academic.domain.classwork.errors import (
    SubmissionCommentTooLongError,
    SubmissionFilesError,
)
from app.shared.clock import to_local
from app.shared.contracts.files import FileRef

MAX_FILES = 10
COMMENT_MAX = 2000
READY = "ready"

SubmissionStatus = Literal["submitted", "late", "missing"]


def clean_comment(value: str | None) -> str | None:
    """Trim the comment; empty clears it, more than 2000 characters fails."""
    text = (value or "").strip()
    if len(text) > COMMENT_MAX:
        raise SubmissionCommentTooLongError(params={"max": COMMENT_MAX})
    return text or None


def check_submission_files(
    file_ids: Sequence[UUID], found: dict[UUID, FileRef], owner_id: UUID
) -> None:
    """1..10 distinct files, each existing, the student's own and ready.

    Raises:
        SubmissionFilesError: The first rule that breaks.
    """
    if not file_ids or len(file_ids) > MAX_FILES or len(set(file_ids)) != len(file_ids):
        raise SubmissionFilesError(params={"reason": "count", "max": MAX_FILES})
    for file_id in file_ids:
        ref = found.get(file_id)
        reason = _problem(ref, owner_id)
        if reason is not None:
            raise SubmissionFilesError(
                params={"file_id": str(file_id), "reason": reason}
            )


def _problem(ref: FileRef | None, owner_id: UUID) -> str | None:
    if ref is None:
        return "not_found"
    if ref.owner_id != owner_id:
        return "not_owner"
    if ref.status != READY:
        return "not_ready"
    return None


def submission_status(
    submitted_at: dt.datetime | None, due_date: dt.date | None
) -> SubmissionStatus:
    """Missing without a submission; late when handed in after the due date.

    The due date is a Tashkent calendar day, so the instant is compared as one.
    """
    if submitted_at is None:
        return "missing"
    if due_date is not None and to_local(submitted_at).date() > due_date:
        return "late"
    return "submitted"
