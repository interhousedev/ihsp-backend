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
from app.shared.actor import Actor, Role
from app.shared.contracts.files import FileScope

MAX_NAME_LENGTH = 255
SNIFF_BYTES = 65536  # libmagic needs more than 1 KiB to recognise OOXML
PRESIGN_PUT_SECONDS = 300
PRESIGN_GET_SECONDS = 60
EXPIRY_GRACE = timedelta(days=14)
EXPIRY_WARNING = timedelta(days=7)
PENDING_TTL = timedelta(hours=24)
PROCESSING_STALE_AFTER = timedelta(minutes=10)
SHA256_BYTES = 32

PDF = "application/pdf"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
PPTX = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
INLINE_TYPES = frozenset({PDF, "image/png", "image/jpeg"})

_ZIP_FALLBACKS = frozenset({"application/zip", "application/octet-stream"})
_TEXT_EXTRA = frozenset({"application/json", "application/xml"})
_LOOSE_DECLARED = frozenset({"", "application/octet-stream"})
_ZIP_MAGIC = b"PK\x03\x04"
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


RULES: dict[str, TypeRule] = {
    ".pdf": TypeRule(PDF, frozenset({PDF}), frozenset({PDF})),
    ".docx": TypeRule(DOCX, frozenset({DOCX}), frozenset({DOCX}), zip_based=True),
    ".pptx": TypeRule(PPTX, frozenset({PPTX}), frozenset({PPTX}), zip_based=True),
    ".xlsx": TypeRule(XLSX, frozenset({XLSX}), frozenset({XLSX}), zip_based=True),
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
}


@dataclass(frozen=True, slots=True)
class FilesLimits:
    """Sizes and quotas (LIMITS__* settings)."""

    student_quota_bytes: int
    staff_quota_bytes: int
    file_max_bytes: int
    ai_text_max_bytes: int

    def quota_for(self, scope: FileScope) -> int | None:
        """Return the quota of a scope, or None when the scope has no quota."""
        if scope == FileScope.STUDENT:
            return self.student_quota_bytes
        if scope == FileScope.STAFF:
            return self.staff_quota_bytes
        return None


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
    if rule.text and normalized in _LOOSE_DECLARED:
        return rule, rule.canonical
    raise TypeNotAllowedError(params={"extension": ext, "content_type": normalized})


def check_size(size: int, max_bytes: int) -> None:
    """Reject empty and too big files."""
    if size < 1:
        raise InvalidSizeError(params={"size": size})
    if size > max_bytes:
        raise FileTooLargeError(params={"size": size, "max_bytes": max_bytes})


def check_checksum(sha256_b64: str) -> str:
    """Return the checksum if it is base64 of a 32-byte SHA-256 digest."""
    try:
        raw = base64.b64decode(sha256_b64, validate=True)
    except ValueError as exc:  # binascii.Error is a ValueError
        raise InvalidChecksumError() from exc
    if len(raw) != SHA256_BYTES:
        raise InvalidChecksumError()
    return sha256_b64


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
    staff_roles = {Role.TEACHER, Role.ADMIN, Role.LMS_ADMIN}
    if staff_roles & actor.roles:
        return FileScope.STAFF
    return FileScope.STUDENT


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
