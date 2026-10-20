"""Errors of homework, attendance, journal and lesson views."""

from app.shared.base_error import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ValidationFailedError,
)


class LessonNotFoundError(NotFoundError):
    """The lesson does not exist or is not visible to the caller."""

    code = "academic/lesson-not-found"
    message_key = "academic-lesson-not-found"


class StudentNotFoundError(NotFoundError):
    """The caller has no student record."""

    code = "academic/student-not-found"
    message_key = "academic-student-not-found"


class JournalNotFoundError(NotFoundError):
    """The subject and audience pair is not in the teacher's journal."""

    code = "academic/journal-not-found"
    message_key = "academic-journal-not-found"


class HomeworkNotFoundError(NotFoundError):
    """The lesson has no homework for this student."""

    code = "homework/not-found"
    message_key = "homework-not-found"


class NotLessonTeacherError(ForbiddenError):
    """Only the lesson's teacher or Administration may do this."""

    code = "academic/not-lesson-teacher"
    message_key = "academic-not-lesson-teacher"


class LessonReassignedError(ForbiddenError):
    """The lesson now belongs to another teacher (bot prompts, UF-BOT-08)."""

    code = "attendance/lesson-reassigned"
    message_key = "attendance-lesson-reassigned"


class NotCuratorError(ForbiddenError):
    """The caller does not curate the group."""

    code = "academic/not-curator"
    message_key = "academic-not-curator"


class AttendanceConflictError(ConflictError):
    """Someone changed the attendance after the caller opened it (ACA-11)."""

    message_key = "attendance-conflict"


class AbsentOutsideRosterError(ValidationFailedError):
    """A student that is not in the lesson's audience was marked."""

    code = "attendance/absent-outside-roster"
    message_key = "attendance-absent-outside-roster"


class AttendanceCancelledLessonError(ValidationFailedError):
    """Attendance cannot be taken for a cancelled lesson."""

    code = "attendance/lesson-cancelled"
    message_key = "attendance-lesson-cancelled"


class ExcuseNotAbsentError(ValidationFailedError):
    """Only an absence can be excused."""

    code = "attendance/excuse-not-absent"
    message_key = "attendance-excuse-not-absent"


class HomeworkTextError(ValidationFailedError):
    """Homework text is empty or too long."""

    code = "homework/text-invalid"
    message_key = "homework-text-invalid"


class HomeworkCancelledLessonError(ValidationFailedError):
    """Homework cannot be set for a cancelled lesson: no student would see it."""

    code = "homework/lesson-cancelled"
    message_key = "homework-lesson-cancelled"


class HomeworkNoteTooLongError(ValidationFailedError):
    """A private note is longer than 1000 characters (WEB-20)."""

    code = "homework/note-too-long"
    message_key = "homework-note-too-long"


class TopicTooLongError(ValidationFailedError):
    """The lesson topic is longer than 300 characters."""

    code = "academic/topic-too-long"
    message_key = "academic-topic-too-long"


class WorkOffTemplateNotFoundError(NotFoundError):
    """The work-off template does not exist or belongs to someone else (WO-1)."""

    code = "work-off/template-not-found"
    message_key = "academic-work-off-template-not-found"


class WorkOffNotFoundError(NotFoundError):
    """The work-off task does not exist (WO-3)."""

    code = "work-off/not-found"
    message_key = "academic-work-off-not-found"


class WorkOffTemplateLimitError(ValidationFailedError):
    """A teacher already has the maximum number of work-off templates (WO-1)."""

    code = "work-off/template-limit"
    message_key = "academic-work-off-template-limit"


class WorkOffTextInvalidError(ValidationFailedError):
    """Work-off text is empty or too long (WO-1, WO-3)."""

    code = "work-off/text-invalid"
    message_key = "academic-work-off-text-invalid"


class WorkOffTextRequiredError(ValidationFailedError):
    """A common work-off needs a template or a text (WO-3)."""

    code = "work-off/text-required"
    message_key = "academic-work-off-text-required"


class WorkOffNotAbsentError(ValidationFailedError):
    """A work-off can only go to a student marked absent (WO-3)."""

    code = "work-off/not-absent"
    message_key = "academic-work-off-not-absent"


class WorkOffStatusInvalidError(ValidationFailedError):
    """The work-off status is not assigned or done (WO-3)."""

    code = "work-off/status-invalid"
    message_key = "academic-work-off-status-invalid"


class TemporaryMarkValueInvalidError(ValidationFailedError):
    """A temporary mark must be on the EMIS scale (TMP-1)."""

    code = "temporary-mark/value-invalid"
    message_key = "academic-temporary-mark-value-invalid"


class TemporaryMarkCommentInvalidError(ValidationFailedError):
    """A temporary mark comment is too long (TMP-1)."""

    code = "temporary-mark/comment-invalid"
    message_key = "academic-temporary-mark-comment-invalid"


class TemporaryMarkNotFoundError(NotFoundError):
    """The student has no temporary mark for the lesson (TMP-1)."""

    code = "temporary-mark/not-found"
    message_key = "academic-temporary-mark-not-found"


class StudentNotInLessonError(ValidationFailedError):
    """The student is not on the lesson's roster (TMP-1)."""

    code = "temporary-mark/student-not-in-lesson"
    message_key = "academic-temporary-mark-student-not-in-lesson"
