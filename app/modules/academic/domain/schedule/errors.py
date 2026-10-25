"""Errors of the academic schedule (terms, groups, rooms, timetable, lessons)."""

from app.shared.base_error import (
    ConflictError,
    ForbiddenError,
    GoneError,
    NotFoundError,
    ValidationFailedError,
)

# - - - Terms - - -


class TermNotFoundError(NotFoundError):
    """The term does not exist."""

    code = "academic/term-not-found"
    message_key = "academic-term-not-found"


class TermOverlapError(ConflictError):
    """The term's dates overlap another term."""

    code = "academic/term-overlap"
    message_key = "academic-term-overlap"


class TermDuplicateError(ConflictError):
    """A term with this academic year and half already exists."""

    code = "academic/term-duplicate"
    message_key = "academic-term-duplicate"


class TermDatesInvalidError(ValidationFailedError):
    """A term must start before it ends."""

    code = "academic/term-dates-invalid"
    message_key = "academic-term-dates-invalid"


class TermControlPeriodsInvalidError(ValidationFailedError):
    """A control period is reversed, outside the term or overlaps the one before."""

    code = "academic/term-control-periods-invalid"
    message_key = "academic-term-control-periods-invalid"


class TermBellsInvalidError(ValidationFailedError):
    """Bell periods are malformed or repeated on a weekday."""

    code = "academic/term-bells-invalid"
    message_key = "academic-term-bells-invalid"


class TermNonStudyDayInvalidError(ValidationFailedError):
    """A non-study day falls outside the term."""

    code = "academic/term-non-study-day-invalid"
    message_key = "academic-term-non-study-day-invalid"


class TermMovedDayInvalidError(ValidationFailedError):
    """A moved day falls on a weekend, or follows a weekday outside Monday-Friday."""

    code = "academic/term-moved-day-invalid"
    message_key = "academic-term-moved-day-invalid"


class NoTermForDateError(ValidationFailedError):
    """No term contains the date of the lesson."""

    code = "academic/no-term-for-date"
    message_key = "academic-no-term-for-date"


class NoBellError(ValidationFailedError):
    """The term has no bell for this period on this weekday."""

    code = "academic/no-bell"
    message_key = "academic-no-bell"


# - - - Groups and students - - -


class GroupNotFoundError(NotFoundError):
    """The group does not exist."""

    code = "academic/group-not-found"
    message_key = "academic-group-not-found"


class GroupNameInvalidError(ValidationFailedError):
    """The group name is empty after normalization."""

    code = "academic/group-name-invalid"
    message_key = "academic-group-name-invalid"


class GroupNameTakenError(ConflictError):
    """An active group already has this name."""

    code = "academic/group-name-taken"
    message_key = "academic-group-name-taken"


class GroupEmisIdTakenError(ConflictError):
    """Another group is already linked to this EMIS group."""

    code = "academic/group-emis-id-taken"
    message_key = "academic-group-emis-id-taken"


class CuratorNotTeacherError(ValidationFailedError):
    """The curator must be a teacher."""

    code = "academic/curator-not-teacher"
    message_key = "academic-curator-not-teacher"


class HeadStudentInvalidError(ValidationFailedError):
    """The head student must be an active student of the group."""

    code = "academic/head-student-invalid"
    message_key = "academic-head-student-invalid"


class NotGroupCuratorError(ForbiddenError):
    """Only the group's curator or Administration may do this."""

    code = "academic/not-group-curator"
    message_key = "academic-not-group-curator"


class SubgroupAssignmentInvalidError(ValidationFailedError):
    """A user in the assignment is not an active student of the group."""

    code = "academic/subgroup-assignment-invalid"
    message_key = "academic-subgroup-assignment-invalid"


class StudentNotFoundError(NotFoundError):
    """The student does not exist."""

    code = "academic/student-not-found"
    message_key = "academic-student-not-found"


class CurriculumNoEmisStudentError(ConflictError):
    """No student of the group has a working EMIS login to read the curriculum with."""

    code = "academic/curriculum-no-emis-student"
    message_key = "academic-curriculum-no-emis-student"


# - - - Subjects and rooms - - -


class SubjectNotFoundError(NotFoundError):
    """The subject does not exist."""

    code = "academic/subject-not-found"
    message_key = "academic-subject-not-found"


class SubjectEmisIdTakenError(ConflictError):
    """Another subject is already linked to this EMIS subject."""

    code = "academic/subject-emis-id-taken"
    message_key = "academic-subject-emis-id-taken"


class SubjectNameInvalidError(ValidationFailedError):
    """A subject needs a name in at least one language."""

    code = "academic/subject-name-invalid"
    message_key = "academic-subject-name-invalid"


class RoomNotFoundError(NotFoundError):
    """The room does not exist."""

    code = "academic/room-not-found"
    message_key = "academic-room-not-found"


class RoomNameInvalidError(ValidationFailedError):
    """The room name is empty."""

    code = "academic/room-name-invalid"
    message_key = "academic-room-name-invalid"


class RoomSlugTakenError(ConflictError):
    """Another room already uses this address."""

    code = "academic/room-slug-taken"
    message_key = "academic-room-slug-taken"


class RoomInUseError(ConflictError):
    """Future lessons still use the room."""

    code = "academic/room-in-use"
    message_key = "academic-room-in-use"


class RoomMergeInvalidError(ValidationFailedError):
    """A room cannot be merged into itself or into an archived room."""

    code = "academic/room-merge-invalid"
    message_key = "academic-room-merge-invalid"


# - - - Timetable and lessons - - -


class EntryNotFoundError(NotFoundError):
    """The timetable entry does not exist."""

    code = "academic/entry-not-found"
    message_key = "academic-entry-not-found"


class EntryInvalidError(ValidationFailedError):
    """The timetable entry (or extra lesson) breaks a rule."""

    code = "academic/entry-invalid"
    message_key = "academic-entry-invalid"


class EntryNotSchoolDayError(ValidationFailedError):
    """Lessons are held Monday to Friday; a Saturday slot is not allowed."""

    code = "academic/entry-not-school-day"
    message_key = "academic-entry-not-school-day"


class LessonNotFoundError(NotFoundError):
    """The lesson does not exist."""

    code = "academic/lesson-not-found"
    message_key = "academic-lesson-not-found"


class TeacherNotFoundError(NotFoundError):
    """The user is not a teacher of the student (or does not exist)."""

    code = "academic/teacher-not-found"
    message_key = "academic-teacher-not-found"


# - - - Import - - -


class ImportInvalidError(ValidationFailedError):
    """The CSV file cannot be read."""

    code = "academic/import-invalid"
    message_key = "academic-import-invalid"


class ImportExpiredError(GoneError):
    """The import preview expired or never existed."""

    code = "academic/import-expired"
    message_key = "academic-import-expired"


# - - - Teaching (a teacher's subject groups) - - -


class NotTeachingGroupError(ForbiddenError):
    """The teacher does not teach this subject to this group (or subgroup)."""

    code = "academic/not-teaching-group"
    message_key = "academic-not-teaching-group"


class StudentNotInGroupError(NotFoundError):
    """The student is not an active student of the group (or subgroup)."""

    code = "academic/student-not-in-group"
    message_key = "academic-student-not-in-group"
