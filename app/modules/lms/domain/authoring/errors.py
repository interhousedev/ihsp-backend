"""Typed errors of the course authoring domain."""

from app.shared.base_error import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ValidationFailedError,
)

# - - - Not found - - -


class CourseNotFoundError(NotFoundError):
    """The course does not exist."""

    code = "lms/course-not-found"
    message_key = "lms-course-not-found"


class StepNotFoundError(NotFoundError):
    """The step does not exist."""

    code = "lms/step-not-found"
    message_key = "lms-step-not-found"


class VideoBlockNotFoundError(NotFoundError):
    """The step has no uploaded video block with this ID."""

    code = "lms/video-not-found"
    message_key = "lms-video-block-not-found"


class RevisionNotFoundError(NotFoundError):
    """The step revision does not exist."""

    code = "lms/revision-not-found"
    message_key = "lms-revision-not-found"


class VersionNotFoundError(NotFoundError):
    """The course version does not exist."""

    code = "lms/version-not-found"
    message_key = "lms-version-not-found"


class StaffMemberNotFoundError(NotFoundError):
    """The user is not on the staff of the course."""

    code = "lms/staff-not-found"
    message_key = "lms-staff-not-found"


class UserNotFoundError(NotFoundError):
    """No active user with this login (contract error type `id/user-not-found`)."""

    code = "id/user-not-found"
    message_key = "lms-user-not-found"


# - - - Permissions - - -


class CoursePermissionError(ForbiddenError):
    """The actor lacks a course permission."""

    code = "lms/permission-denied"
    message_key = "lms-permission-denied"


# - - - Conflicts - - -


class DraftConflictError(ConflictError):
    """Stale `lock_version`; `params.theirs` carries the current draft."""

    code = "common/conflict"
    message_key = "lms-draft-conflict"


class DraftChangedError(ConflictError):
    """The draft changed after the publisher reviewed it (LMS-13)."""

    code = "lms/draft-changed"
    message_key = "lms-draft-changed"


class SlugTakenError(ConflictError):
    """Another course already uses the slug."""

    code = "lms/slug-taken"
    message_key = "lms-slug-taken"


class StaffAlreadyExistsError(ConflictError):
    """The user is already on the staff of the course."""

    code = "lms/staff-exists"
    message_key = "lms-staff-exists"


class LastManagerError(ConflictError):
    """The last holder of `manage_staff` cannot be removed (UF-LMS-07)."""

    code = "lms/last-manager"
    message_key = "lms-last-manager"


# - - - Validation - - -


class SlugInvalidError(ValidationFailedError):
    """The slug does not match `[a-z0-9-]{3,60}`."""

    code = "lms/slug-invalid"
    message_key = "lms-slug-invalid"


class TitleInvalidError(ValidationFailedError):
    """The title is empty or too long."""

    code = "lms/title-invalid"
    message_key = "lms-title-invalid"


class StaffInvalidError(ValidationFailedError):
    """The role or the permissions of a staff member are invalid."""

    code = "lms/staff-invalid"
    message_key = "lms-staff-invalid"


class OutlineError(ValidationFailedError):
    """An outline operation does not apply to the current outline."""

    code = "lms/outline-invalid"
    message_key = "lms-outline-invalid"


class PlanInvalidError(ValidationFailedError):
    """A course plan breaks a limit (sections, steps, briefs) or has a wrong shape."""

    code = "lms/plan-invalid"
    message_key = "lms-plan-invalid"


class ContentInvalidError(ValidationFailedError):
    """Step content is invalid (for example duplicate IDs)."""

    code = "lms/content-invalid"
    message_key = "lms-content-invalid"


class FileMissingError(ValidationFailedError):
    """Content or settings reference a file that does not exist."""

    code = "lms/file-missing"
    message_key = "lms-file-missing"


class NothingToPublishError(ValidationFailedError):
    """The draft equals the live version."""

    code = "lms/nothing-to-publish"
    message_key = "lms-nothing-to-publish"


class NoLiveVersionError(ValidationFailedError):
    """There is no live state to go back to."""

    code = "lms/no-live-version"
    message_key = "lms-no-live-version"


class InviteNotApplicableError(ValidationFailedError):
    """Only invite-only courses have an invite code."""

    code = "lms/invite-not-applicable"
    message_key = "lms-invite-not-applicable"
