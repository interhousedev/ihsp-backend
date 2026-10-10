"""Typed errors of the learning side of the LMS (LMS-14 to LMS-20)."""

from app.shared.base_error import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ValidationFailedError,
)

# - - - Not found - - -


class CourseNotFoundError(NotFoundError):
    """The course does not exist or is not visible to the actor."""

    code = "lms/course-not-found"
    message_key = "lms-learn-course-not-found"


class StepNotFoundError(NotFoundError):
    """The step is not part of the live version of the course."""

    code = "lms/step-not-found"
    message_key = "lms-learn-step-not-found"


class BlockNotFoundError(NotFoundError):
    """The step has no block of the requested kind with this id."""

    code = "lms/block-not-found"
    message_key = "lms-learn-block-not-found"


class VideoNotFoundError(NotFoundError):
    """The block is not an uploaded video."""

    code = "lms/video-not-found"
    message_key = "lms-learn-video-not-found"


class CardNotFoundError(NotFoundError):
    """The flash card does not exist (any more) in the step."""

    code = "lms/card-not-found"
    message_key = "lms-learn-card-not-found"


class AttemptNotFoundError(NotFoundError):
    """The attempt does not exist or belongs to someone else."""

    code = "lms/attempt-not-found"
    message_key = "lms-learn-attempt-not-found"


class InviteNotValidError(NotFoundError):
    """Wrong or rotated invite code (UF-LMS-02, 1a)."""

    code = "lms/invite-not-valid"
    message_key = "lms-learn-invite-not-valid"


# - - - Permissions - - -


class NotEnrolledError(ForbiddenError):
    """The student is not enrolled in the course."""

    code = "lms/not-enrolled"
    message_key = "lms-learn-not-enrolled"


class CoursePermissionError(ForbiddenError):
    """The actor lacks a course staff permission."""

    code = "lms/permission-denied"
    message_key = "lms-learn-permission-denied"


# - - - Attempts - - -


class NoAttemptsLeftError(ConflictError):
    """The attempts limit of the test is used up (UF-LMS-04, 2a)."""

    code = "lms/no-attempts-left"
    message_key = "lms-learn-no-attempts-left"


class AttemptCooldownError(ConflictError):
    """The pause between attempts is not over; `params.available_at` says when."""

    code = "lms/attempt-cooldown"
    message_key = "lms-learn-attempt-cooldown"


class AttemptClosedError(ConflictError):
    """The attempt is already submitted or its time is over."""

    code = "lms/attempt-closed"
    message_key = "lms-learn-attempt-closed"


class AttemptNotSubmittedError(ConflictError):
    """The attempt has no result yet."""

    code = "lms/attempt-not-submitted"
    message_key = "lms-learn-attempt-not-submitted"


class AttemptStartConflictError(ConflictError):
    """Two requests started the same attempt at once and the retry failed too."""

    code = "lms/attempt-start-conflict"
    message_key = "lms-learn-attempt-start-conflict"


# - - - Validation - - -


class AnswerInvalidError(ValidationFailedError):
    """An answer does not fit the question or the attempt variant."""

    code = "lms/answer-invalid"
    message_key = "lms-learn-answer-invalid"


class ScoreInvalidError(ValidationFailedError):
    """The overridden score is outside 0..max_score."""

    code = "lms/score-invalid"
    message_key = "lms-learn-score-invalid"


class PreviewAttemptError(ValidationFailedError):
    """Preview attempts are not reviewed or graded by staff."""

    code = "lms/attempt-preview"
    message_key = "lms-learn-attempt-preview"


class AttemptNumberTakenError(Exception):
    """A repository signals a unique (user, step, block, attempt_no) conflict."""
