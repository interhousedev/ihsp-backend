"""Enumerations of the notebooks module (every value of every phase, § 4.1)."""

from enum import StrEnum


class NotebookOrigin(StrEnum):
    """How a notebook came to be: written by the student or kept up by the system."""

    MANUAL = "manual"
    SUBJECT_AUTO = "subject_auto"
    LESSON_AUTO = "lesson_auto"
    COURSE = "course"  # the workspace of an LMS course, shared by its staff
    COURSE_STUDENT = "course_student"  # an enrolled student's notebook of a course

    @property
    def is_auto(self) -> bool:
        """True for notebooks whose lesson sources the system maintains."""
        return self in (NotebookOrigin.SUBJECT_AUTO, NotebookOrigin.LESSON_AUTO)


class SourceKind(StrEnum):
    """Where the text of a source comes from (§ 3.2.1)."""

    FILE = "file"
    CHAT = "chat"
    LESSON_RESOURCE = "lesson_resource"
    FLASHCARD_SET = "flashcard_set"
    LMS_STEP = "lms_step"
    TEXT = "text"
    NOTE = "note"
    URL = "url"
    WEB_RESULT = "web_result"
    LIBRARY_ITEM = "library_item"  # a book or material, or a page range of it
    LIBRARY_NOTES = "library_notes"  # the student's own highlights and notes in it


class SourceStatus(StrEnum):
    """Processing state of a source."""

    PENDING = "pending"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"
    UNAVAILABLE = "unavailable"
    STALE = "stale"

    @property
    def usable(self) -> bool:
        """Ready and stale sources are used for chat and Studio."""
        return self in (SourceStatus.READY, SourceStatus.STALE)


class SourceFailure(StrEnum):
    """Machine code of why a source failed (translated by the web app)."""

    UNSUPPORTED_TYPE = "unsupported_type"
    NO_TEXT = "no_text"
    NO_TRANSCRIPT = "no_transcript"  # a YouTube video without captions (or disabled)
    TOO_LARGE = "too_large"
    FETCH_FAILED = "fetch_failed"
    FORBIDDEN = "forbidden"
    DELETED = "deleted"
    PROVIDER_ERROR = "provider_error"
    ACCESS_REVOKED = "access_revoked"


class GuideStatus(StrEnum):
    """State of a source guide."""

    NONE = "none"
    BUILDING = "building"
    READY = "ready"
    FAILED = "failed"


class SummaryStatus(StrEnum):
    """State of a notebook's automatic summary."""

    NONE = "none"
    STALE = "stale"
    BUILDING = "building"
    READY = "ready"
    FAILED = "failed"


class MessageRole(StrEnum):
    """Who wrote a notebook chat message."""

    USER = "user"
    ASSISTANT = "assistant"


class ChatStyle(StrEnum):
    """Answer style of the notebook chat (§ 3.3.6)."""

    DEFAULT = "default"
    LEARNING_GUIDE = "learning_guide"
    CUSTOM = "custom"


class ChatLength(StrEnum):
    """Answer length of the notebook chat."""

    DEFAULT = "default"
    SHORTER = "shorter"
    LONGER = "longer"


class ChatLanguage(StrEnum):
    """Answer language of the notebook chat; ``auto`` follows the user's locale."""

    AUTO = "auto"
    UZ = "uz"
    RU = "ru"
    EN = "en"


class ArtifactKind(StrEnum):
    """Studio output kinds (the audio kind is reserved: it is never generated)."""

    REPORT = "report"
    MIND_MAP = "mind_map"
    FLASHCARDS = "flashcards"
    QUIZ = "quiz"
    DATA_TABLE = "data_table"
    SLIDES = "slides"
    INFOGRAPHIC = "infographic"
    EXERCISE = "exercise"  # practice set: passage + typed questions
    AUDIO_OVERVIEW = "audio_overview"
    COURSE_PLAN = "course_plan"  # course workspaces only: sections, steps, goals
    LESSON_DRAFT = "lesson_draft"  # course workspaces only: the blocks of one step

    @property
    def is_course_kind(self) -> bool:
        """True for the outputs that exist only in a course workspace."""
        return self in (ArtifactKind.COURSE_PLAN, ArtifactKind.LESSON_DRAFT)


class ArtifactStatus(StrEnum):
    """Lifecycle of a Studio output."""

    QUEUED = "queued"
    GENERATING = "generating"
    READY = "ready"
    FAILED = "failed"
    CANCELED = "canceled"


class ReportFormat(StrEnum):
    """Markdown report formats."""

    CONSPECT = "conspect"
    STUDY_GUIDE = "study_guide"
    BRIEFING = "briefing"
    FAQ = "faq"
    TIMELINE = "timeline"
    ARTICLE = "article"
    CUSTOM = "custom"


class ArtifactFailure(StrEnum):
    """Machine code of why an output failed (``artifacts.error.code``)."""

    PROVIDER_ERROR = "provider_error"
    INVALID_OUTPUT = "invalid_output"
    NO_CONTENT = "no_content"
    LIMIT_REACHED = "limit_reached"
    TIMEOUT = "timeout"
    CANCELED = "canceled"
    ACCESS_REVOKED = "access_revoked"
