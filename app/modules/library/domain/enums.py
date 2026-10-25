"""Enumerations of the library module (every value of every phase, doc § 6.1)."""

from enum import StrEnum


class ItemKind(StrEnum):
    """Three kinds of catalogue item (D1)."""

    EXTERNAL = "external"
    BOOK = "book"
    MATERIAL = "material"


class ItemType(StrEnum):
    """One list of types for all kinds (doc § 3.2)."""

    TEXTBOOK = "textbook"
    MANUAL = "manual"
    FICTION = "fiction"
    POETRY = "poetry"
    DRAMA = "drama"
    NONFICTION = "nonfiction"
    REFERENCE = "reference"
    DICTIONARY = "dictionary"
    LAB_MANUAL = "lab_manual"
    PROBLEM_BOOK = "problem_book"
    ARTICLE = "article"
    TEACHING_MATERIAL = "teaching_material"
    PRESENTATION = "presentation"
    WORKSHEET = "worksheet"
    LECTURE_NOTES = "lecture_notes"
    NOTES = "notes"
    PRACTICE_SET = "practice_set"
    FORMULA_SHEET = "formula_sheet"
    OTHER = "other"


class ItemStatus(StrEnum):
    """Lifecycle of an item (doc § 3.5)."""

    DRAFT = "draft"
    PENDING_REVIEW = "pending_review"
    CHANGES_REQUESTED = "changes_requested"
    PUBLISHED = "published"
    HELD = "held"
    REJECTED = "rejected"
    UNPUBLISHED = "unpublished"
    GONE = "gone"


class Visibility(StrEnum):
    """Who may see a published item."""

    PUBLIC = "public"
    LYCEUM = "lyceum"
    HIDDEN = "hidden"


class ItemLanguage(StrEnum):
    """Language and script of an item."""

    UZ_LATN = "uz_latn"
    UZ_CYRL = "uz_cyrl"
    RU = "ru"
    EN = "en"
    QQ = "qq"
    OTHER = "other"


class Rights(StrEnum):
    """Rights class of a hosted book (LIB-3)."""

    PUBLIC_DOMAIN = "public_domain"
    OPEN_LICENSE = "open_license"
    PERMISSION = "permission"
    OFFICIAL = "official"


class MaterialLicence(StrEnum):
    """Licence the uploader of a material grants."""

    ALL_RIGHTS_RESERVED = "all_rights_reserved"
    CC_BY = "cc_by"
    CC_BY_SA = "cc_by_sa"
    CC_BY_NC = "cc_by_nc"
    CC_BY_NC_SA = "cc_by_nc_sa"


class UploaderRole(StrEnum):
    """Role of the uploader at upload time (snapshot)."""

    STUDENT = "student"
    TEACHER = "teacher"
    LIBRARIAN = "librarian"
    ADMIN = "admin"


class Approval(StrEnum):
    """Who published a material."""

    AUTO_TEACHER = "auto_teacher"
    LIBRARIAN = "librarian"
    ADMIN = "admin"


class FileFormat(StrEnum):
    """Format of an item file."""

    PDF = "pdf"
    EPUB = "epub"
    MD = "md"
    TXT = "txt"
    DOCX = "docx"
    PPTX = "pptx"


class TextStatus(StrEnum):
    """State of the text extraction of a file."""

    NONE = "none"
    PENDING = "pending"
    READY = "ready"
    NO_TEXT = "no_text"
    FAILED = "failed"


class SubjectRole(StrEnum):
    """How an item relates to a subject."""

    TEXTBOOK = "textbook"
    CORE = "core"
    SUPPLEMENTARY = "supplementary"
    REFERENCE = "reference"


class ListScope(StrEnum):
    """Audience of a reading list."""

    SUBJECT = "subject"
    GROUPS = "groups"
    SCHOOL = "school"


class ListStatus(StrEnum):
    """State of a reading list."""

    DRAFT = "draft"
    PUBLISHED = "published"
    ARCHIVED = "archived"


class Importance(StrEnum):
    """Importance label of a reading-list entry."""

    ESSENTIAL = "essential"
    RECOMMENDED = "recommended"
    FURTHER = "further"


class ReportReason(StrEnum):
    """Why a user reports an item."""

    WRONG_CONTENT = "wrong_content"
    COPYRIGHT = "copyright"
    INAPPROPRIATE = "inappropriate"
    PERSONAL_DATA = "personal_data"
    EXAM_LEAK = "exam_leak"
    SPAM = "spam"
    OTHER = "other"


class ReportStatus(StrEnum):
    """State of a report."""

    OPEN = "open"
    UPHELD = "upheld"
    DISMISSED = "dismissed"


class EventKind(StrEnum):
    """Kinds of the append-only item history."""

    CREATED = "created"
    SUBMITTED = "submitted"
    APPROVED = "approved"
    CHANGES_REQUESTED = "changes_requested"
    REJECTED = "rejected"
    HELD = "held"
    RESTORED = "restored"
    UNPUBLISHED = "unpublished"
    EDITED = "edited"
    VERSION_ADDED = "version_added"
    HIDDEN = "hidden"
    RIGHTS_CHANGED = "rights_changed"
    SYNCED = "synced"


class SanctionKind(StrEnum):
    """Sanctions Administration can set."""

    WARNING = "warning"
    UPLOAD_BAN = "upload_ban"


class SuggestionStatus(StrEnum):
    """State of a book suggestion."""

    NEW = "new"
    ACCEPTED = "accepted"
    DECLINED = "declined"


class ShelfState(StrEnum):
    """Where an item is on a user's shelf."""

    WANT = "want"
    READING = "reading"
    DONE = "done"


class AnnotationKind(StrEnum):
    """Kinds of reader annotation."""

    HIGHLIGHT = "highlight"
    NOTE = "note"
    BOOKMARK = "bookmark"


class AnnotationColor(StrEnum):
    """Highlight colours."""

    YELLOW = "yellow"
    GREEN = "green"
    BLUE = "blue"
    PINK = "pink"


class ExternalSource(StrEnum):
    """External catalogues."""

    UNILIBRARY = "unilibrary"


class ExternalAccess(StrEnum):
    """Access class of an external record (`resource_modifier_id` 1, 2, 3)."""

    OPEN = "open"
    PARTIAL = "partial"
    CLOSED = "closed"


class StatusReasonCode(StrEnum):
    """System codes of `item.status_reason`; a librarian may write own words instead.

    The API publishes this enum so clients can translate the codes; any other value is
    free text written by a librarian or a teacher, shown as it is.
    """

    WITHDRAWN_BY_OWNER = "withdrawn_by_owner"
    REPORTED = "reported"
    SUPERSEDED = "superseded"
    ACCOUNT_CLOSED = "account_closed"
    UNPUBLISHED = "unpublished"
    TAKEDOWN = "takedown"
