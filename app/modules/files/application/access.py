"""Who may see or change a file."""

from app.modules.files.domain.errors import (
    FileDeletedError,
    StoredFileNotFoundError,
)
from app.modules.files.domain.policy import may_read
from app.modules.files.domain.status import FileStatus
from app.modules.files.domain.stored_file import StoredFile
from app.shared.actor import Actor
from app.shared.base_error import ForbiddenError
from app.shared.contracts.files import FileScope

OWNER_EDITABLE_SCOPES = frozenset({FileScope.STUDENT, FileScope.STAFF})


def can_read(file: StoredFile, actor: Actor) -> bool:
    """The owner and administrators may read a file (librarians: library files)."""
    return may_read(file, actor)


def require_readable(file: StoredFile | None, actor: Actor) -> StoredFile:
    """Return the file or raise NotFound (hidden) or Gone (deleted)."""
    if file is None or not can_read(file, actor):
        raise StoredFileNotFoundError()
    if file.status == FileStatus.DELETED:
        raise FileDeletedError()
    return file


def require_owned(file: StoredFile | None, actor: Actor) -> StoredFile:
    """Return the file if the actor owns it and it is not deleted."""
    if (
        file is None
        or file.status == FileStatus.DELETED
        or not file.is_owned_by(actor.user_id)
    ):
        raise StoredFileNotFoundError()
    return file


def require_owner_editable(file: StoredFile | None, actor: Actor) -> StoredFile:
    """Owner operations are limited to student and staff files.

    Course, mail and system files are managed by their own modules.
    """
    owned = require_owned(file, actor)
    if owned.scope not in OWNER_EDITABLE_SCOPES:
        raise ForbiddenError()
    return owned
