"""Upload rules: names, types, sizes, quotas, keys and retention (FILE-2 to FILE-6)."""

import base64
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import PurePosixPath
from uuid import UUID

from app.modules.files.domain.errors import (
    FileTooLargeError,
    InvalidChecksumError,
    InvalidFileNameError,
    InvalidSizeError,
    TypeNotAllowedError,
)
from app.modules.files.domain.stored_file import StoredFile
from app.shared.actor import Actor, Role
from app.shared.base_error import ForbiddenError
from app.shared.contracts.files import FilePurpose, FileScope

MAX_NAME_LENGTH = 255
SNIFF_BYTES = 65536  # libmagic needs more than 1 KiB to recognise OOXML
PRESIGN_PUT_SECONDS = 300
PRESIGN_GET_SECONDS = 60
MAX_PRESIGN_GET_SECONDS = 3600  # longest ``ttl_seconds`` another module may ask for
EXPIRY_GRACE = timedelta(days=14)
EXPIRY_WARNING = timedelta(days=7)
PENDING_TTL = timedelta(hours=24)
PROCESSING_STALE_AFTER = timedelta(minutes=10)
SHA256_BYTES = 32

PDF = "application/pdf"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
PPTX = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
EPUB = "application/epub+zip"
MP4 = "video/mp4"
WEBM = "video/webm"
MOV = "video/quicktime"
INLINE_TYPES = frozenset({PDF, "image/png", "image/jpeg", MP4, WEBM, MOV})

_ZIP_FALLBACKS = frozenset({"application/zip", "application/octet-stream"})
_TEXT_EXTRA = frozenset({"application/json", "application/xml"})
_LOOSE_DECLARED = frozenset({"", "application/octet-stream"})
_ZIP_MAGIC = b"PK\x03\x04"
MB = 1024 * 1024
GB = 1024 * MB
LIBRARY_PURPOSES = frozenset(
    {
        FilePurpose.LIBRARY_BOOK,
        FilePurpose.LIBRARY_COVER,
        FilePurpose.LIBRARY_MATERIAL,
    }
)
LIBRARIAN_ONLY_PURPOSES = frozenset(
    {FilePurpose.LIBRARY_BOOK, FilePurpose.LIBRARY_COVER}
)
VIDEO_EXTENSIONS = frozenset({".mp4", ".webm", ".mov"})
VIDEO_PURPOSES = frozenset({FilePurpose.LMS_VIDEO})
VIDEO_UPLOAD_ROLES = frozenset(
    {Role.TEACHER, Role.ADMIN, Role.LMS_ADMIN, Role.LMS_CREATOR}
)
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_SAFE_EXTENSION = re.compile(r"\.[a-z0-9]{1,10}")


@dataclass(frozen=True, slots=True)
class TypeRule:
    """What one allowed file extension accepts."""

    canonical: str
    declared: frozenset[str]
    detected: frozenset[str]
    text: bool = False
    zip_based: bool = False
    loose_declared: bool = False  # browsers often send no type for it


RULES: dict[str, TypeRule] = {
    ".pdf": TypeRule(PDF, frozenset({PDF}), frozenset({PDF})),
    ".docx": TypeRule(DOCX, frozenset({DOCX}), frozenset({DOCX}), zip_based=True),
    ".pptx": TypeRule(PPTX, frozenset({PPTX}), frozenset({PPTX}), zip_based=True),
    ".xlsx": TypeRule(XLSX, frozenset({XLSX}), frozenset({XLSX}), zip_based=True),
    ".epub": TypeRule(
        EPUB,
        frozenset({EPUB}),
        frozenset({EPUB}),
        zip_based=True,
        loose_declared=True,
    ),
    ".txt": TypeRule(
        "text/plain", frozenset({"text/plain"}), frozenset({"text/plain"}), text=True
    ),
    ".md": TypeRule(
        "text/markdown",
        frozenset({"text/markdown", "text/x-markdown", "text/plain"}),
        frozenset({"text/plain"}),
        text=True,
    ),
    ".png": TypeRule("image/png", frozenset({"image/png"}), frozenset({"image/png"})),
    ".jpg": TypeRule(
        "image/jpeg", frozenset({"image/jpeg"}), frozenset({"image/jpeg"})
    ),
    ".jpeg": TypeRule(
        "image/jpeg", frozenset({"image/jpeg"}), frozenset({"image/jpeg"})
    ),
    ".webp": TypeRule(
        "image/webp", frozenset({"image/webp"}), frozenset({"image/webp"})
    ),
    # Audio (gathered web materials, transcribed by the media model).
    ".mp3": TypeRule(
        "audio/mpeg", frozenset({"audio/mpeg", "audio/mp3"}), frozenset({"audio/mpeg"})
    ),
    ".m4a": TypeRule(
        "audio/mp4",
        frozenset({"audio/mp4", "audio/x-m4a"}),
        frozenset({"audio/mp4", "audio/x-m4a", "video/mp4"}),
        loose_declared=True,
    ),
    ".ogg": TypeRule(
        "audio/ogg",
        frozenset({"audio/ogg"}),
        frozenset({"audio/ogg", "application/ogg"}),
    ),
    ".wav": TypeRule(
        "audio/wav",
        frozenset({"audio/wav", "audio/x-wav"}),
        frozenset({"audio/wav", "audio/x-wav", "audio/vnd.wave"}),
    ),
    # Videos are only accepted for ``VIDEO_PURPOSES`` (``check_purpose_extension``).
    ".mp4": TypeRule(
        MP4,
        frozenset({MP4}),
        frozenset({MP4, MOV, "video/x-m4v"}),
        loose_declared=True,
    ),
    ".webm": TypeRule(
        WEBM,
        frozenset({WEBM}),
        frozenset({WEBM, "video/x-matroska"}),
        loose_declared=True,
    ),
    ".mov": TypeRule(
        MOV,
        frozenset({MOV, MP4}),
        frozenset({MOV, MP4}),
        loose_declared=True,
    ),
}


@dataclass(frozen=True, slots=True)
class FilesLimits:
    """Sizes and quotas (LIMITS__* settings)."""

    student_quota_bytes: int
    staff_quota_bytes: int
    file_max_bytes: int
    ai_text_max_bytes: int
    library_file_max_bytes: int = 300 * MB  # LIBRARY__FILE_MAX_BYTES
    library_student_quota_bytes: int = 300 * MB  # LIBRARY__STUDENT_QUOTA_BYTES
    library_teacher_quota_bytes: int = 2 * GB  # LIBRARY__TEACHER_QUOTA_BYTES
    lms_video_max_bytes: int = 500 * MB  # FILES__LMS_VIDEO_MAX_MB

    def max_bytes_for(self, scope: FileScope) -> int:
        """Return the size limit of one file in the scope."""
        if scope == FileScope.LIBRARY:
            return self.library_file_max_bytes
        return self.file_max_bytes

    def max_bytes_for_purpose(self, purpose: FilePurpose, scope: FileScope) -> int:
        """Return the size limit of one file of the purpose."""
        if purpose in VIDEO_PURPOSES:
            return self.lms_video_max_bytes
        return self.max_bytes_for(scope)

    def quota_for(self, scope: FileScope) -> int | None:
        """Return the quota of a scope, or None when the scope has no quota.

        The library scope has quotas that depend on who uploads: see
        ``quota_for_actor``.
        """
        if scope == FileScope.STUDENT:
            return self.student_quota_bytes
        if scope == FileScope.STAFF:
            return self.staff_quota_bytes
        return None

    def quota_for_actor(self, scope: FileScope, actor: Actor) -> int | None:
        """Return the quota the actor's uploads in the scope count against.

        In the library scope librarians and administrators have none, teachers have
        their own quota, everyone else the student one; it is separate from FILE-5.
        """
        if scope != FileScope.LIBRARY:
            return self.quota_for(scope)
        if is_librarian(actor):
            return None
        if actor.has(Role.TEACHER):
            return self.library_teacher_quota_bytes
        return self.library_student_quota_bytes


def normalize_name(raw: str) -> str:
    """Strip any path and control characters; reject empty or too long names."""
    name = raw.replace("\\", "/").rsplit("/", 1)[-1]
    name = _CONTROL.sub("", name).strip()
    if not name or name in {".", ".."} or len(name) > MAX_NAME_LENGTH:
        raise InvalidFileNameError(params={"max_length": MAX_NAME_LENGTH})
    return name


def extension_of(name: str) -> str:
    """Return the lower-case extension with its dot, or an empty string."""
    return PurePosixPath(name).suffix.lower()


def key_extension(name: str) -> str:
    """Return a safe extension for the storage key (never the user's text)."""
    ext = extension_of(name)
    return ext if _SAFE_EXTENSION.fullmatch(ext) else ""


def normalize_content_type(value: str) -> str:
    """Lower-case a declared Content-Type and drop its parameters."""
    return value.split(";", 1)[0].strip().lower()


def check_declared(name: str, declared: str) -> tuple[TypeRule, str]:
    """Check extension and declared type; return the rule and the type to sign."""
    ext = extension_of(name)
    rule = RULES.get(ext)
    if rule is None:
        raise TypeNotAllowedError(params={"extension": ext})
    normalized = normalize_content_type(declared)
    if normalized in rule.declared:
        return rule, normalized
    if (rule.text or rule.loose_declared) and normalized in _LOOSE_DECLARED:
        return rule, rule.canonical
    raise TypeNotAllowedError(params={"extension": ext, "content_type": normalized})


def check_size(size: int, max_bytes: int) -> None:
    """Reject empty and too big files."""
    if size < 1:
        raise InvalidSizeError(params={"size": size})
    if size > max_bytes:
        raise FileTooLargeError(
            params={"size": size, "max_bytes": max_bytes, "max_mb": max_bytes // MB}
        )


def check_checksum(sha256_b64: str) -> str:
    """Return the checksum if it is base64 of a 32-byte SHA-256 digest."""
    try:
        raw = base64.b64decode(sha256_b64, validate=True)
    except ValueError as exc:  # binascii.Error is a ValueError
        raise InvalidChecksumError() from exc
    if len(raw) != SHA256_BYTES:
        raise InvalidChecksumError()
    return sha256_b64


def checksum_hex(sha256_b64: str) -> str | None:
    """Return the lower-case hex of a stored base64 SHA-256, or None if invalid."""
    try:
        raw = base64.b64decode(sha256_b64, validate=True)
    except ValueError:
        return None
    return raw.hex() if len(raw) == SHA256_BYTES else None


def detected_matches(rule: TypeRule, detected: str, head: bytes) -> bool:
    """Return True if the sniffed type is consistent with the extension's rule."""
    if detected in rule.detected:
        return True
    if rule.text:
        return detected.startswith("text/") or detected in _TEXT_EXTRA
    if rule.zip_based:
        return detected in _ZIP_FALLBACKS and head.startswith(_ZIP_MAGIC)
    return False


def rule_for_name(name: str) -> TypeRule | None:
    """Return the allowed-type rule of a file name, if its extension is allowed."""
    return RULES.get(extension_of(name))


def scope_for(actor: Actor) -> FileScope:
    """Students without a staff role use the student scope; everyone else staff."""
    staff_roles = {Role.TEACHER, Role.ADMIN, Role.LMS_ADMIN, Role.LMS_CREATOR}
    if staff_roles & actor.roles:
        return FileScope.STAFF
    return FileScope.STUDENT


def is_librarian(actor: Actor) -> bool:
    """Librarians and administrators run the library."""
    return actor.has(Role.LIBRARIAN) or actor.has(Role.ADMIN)


def scope_for_purpose(purpose: FilePurpose, actor: Actor) -> FileScope:
    """Library purposes live in the library scope; the rest follow the actor."""
    if purpose in LIBRARY_PURPOSES:
        return FileScope.LIBRARY
    return scope_for(actor)


def check_upload_role(purpose: FilePurpose, actor: Actor) -> None:
    """Books and covers: librarians and administrators; lesson videos: course staff."""
    if purpose in LIBRARIAN_ONLY_PURPOSES and not is_librarian(actor):
        raise ForbiddenError(params={"purpose": purpose.value})
    if purpose in VIDEO_PURPOSES and not (VIDEO_UPLOAD_ROLES & actor.roles):
        raise ForbiddenError(params={"purpose": purpose.value})


def check_purpose_extension(purpose: FilePurpose, name: str) -> None:
    """Videos only for video purposes, and video purposes only take videos."""
    is_video = extension_of(name) in VIDEO_EXTENSIONS
    if is_video != (purpose in VIDEO_PURPOSES):
        raise TypeNotAllowedError(
            params={"extension": extension_of(name), "purpose": purpose.value}
        )


def check_scope_purpose(scope: FileScope, purpose: FilePurpose) -> None:
    """`library_*` purposes belong to the library scope, and only they do."""
    if (purpose in LIBRARY_PURPOSES) != (scope == FileScope.LIBRARY):
        raise TypeNotAllowedError(
            params={"purpose": purpose.value, "scope": scope.value}
        )


def may_read(file: StoredFile, actor: Actor) -> bool:
    """The owner and administrators read a file; librarians also read library files.

    Everyone else gets library files from the library, which checks its own rules.
    """
    if file.is_owned_by(actor.user_id) or actor.has(Role.ADMIN):
        return True
    return file.scope == FileScope.LIBRARY and actor.has(Role.LIBRARIAN)


def month_label(now: datetime) -> str:
    """Return ``yyyy-mm`` for keys of files that belong to no term."""
    return now.astimezone(UTC).strftime("%Y-%m")


def key_for(scope: FileScope, label: str, file_id: UUID, ext: str) -> str:
    """Build the S3 key: ``{scope}/{label}/{file_id}{ext}``."""
    return f"{scope.value}/{label}/{file_id}{ext}"


def inline_allowed(content_type: str) -> bool:
    """Only PDFs and images may open inline; everything else is downloaded."""
    return content_type in INLINE_TYPES


def expiry_date(term_end: date) -> date:
    """Last day student files of a term are kept (term end + 14 days)."""
    return term_end + EXPIRY_GRACE


def is_term_expired(term_end: date, today: date) -> bool:
    """True once the whole expiry day has passed."""
    return expiry_date(term_end) < today


def in_warning_window(term_end: date, today: date) -> bool:
    """True from 7 days before the expiry day until the expiry day itself."""
    expiry = expiry_date(term_end)
    return expiry - EXPIRY_WARNING <= today <= expiry
