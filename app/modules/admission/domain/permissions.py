"""Admission permission vocabulary, built-in sub-roles and the kind allow-list."""

from enum import StrEnum
from typing import Final, Literal

from app.shared.actor import Role


class Permission(StrEnum):
    """What a staff member or owner may do with one student's data."""

    PROFILE_READ = "profile:read"
    PROFILE_COMMENT = "profile:comment"
    WORDS_READ = "words:read"
    WORDS_COMMENT = "words:comment"
    ACTIVITIES_READ = "activities:read"
    ACTIVITIES_COMMENT = "activities:comment"
    LIST_READ = "list:read"
    LIST_COMMENT = "list:comment"
    ESSAYS_READ = "essays:read"
    ESSAYS_COMMENT = "essays:comment"
    NOTES_STAFF = "notes:staff"
    DOCUMENTS_READ = "documents:read"
    DOCUMENTS_ATTACH = "documents:attach"
    DOCUMENTS_REVIEW = "documents:review"
    CONFIDENTIAL_READ = "confidential:read"
    DEADLINES_MANAGE = "deadlines:manage"
    FINANCE_READ = "finance:read"
    AFFORDABILITY_SIGN_OFF = "affordability:sign_off"
    TRANSCRIPTS_FULFIL = "transcripts:fulfil"
    TRANSCRIPTS_OVERSEE = "transcripts:oversee"
    STUDENTS_ASSIGN = "students:assign"
    LABELS_OVERRIDE = "labels:override"
    ESTIMATES_VIEW_UNCALIBRATED = "estimates:view_uncalibrated"
    CATALOG_CURATE = "catalog:curate"
    OPPORTUNITIES_MODERATE = "opportunities:moderate"


P = Permission
StaffKind = Literal["counselor", "mentor", "transcript_officer"]

# The global role a sub-role kind needs (checked live on every resolve).
KIND_ROLE: Final[dict[str, Role]] = {
    "counselor": Role.COUNSELOR,
    "mentor": Role.MENTOR,
    "transcript_officer": Role.TRANSCRIPT_OFFICER,
}

_MENTOR_FORBIDDEN: Final = frozenset(
    {
        P.DOCUMENTS_READ,
        P.DOCUMENTS_ATTACH,
        P.DOCUMENTS_REVIEW,
        P.CONFIDENTIAL_READ,
        P.FINANCE_READ,
        P.AFFORDABILITY_SIGN_OFF,
        P.NOTES_STAFF,
        P.LABELS_OVERRIDE,
        P.STUDENTS_ASSIGN,
        P.TRANSCRIPTS_FULFIL,
        P.TRANSCRIPTS_OVERSEE,
    }
)
_STAFF: Final = frozenset(P)

KIND_ALLOW_LIST: Final[dict[str, frozenset[Permission]]] = {
    "counselor": _STAFF - {P.TRANSCRIPTS_FULFIL},
    "mentor": _STAFF - _MENTOR_FORBIDDEN,
    "transcript_officer": frozenset({P.TRANSCRIPTS_FULFIL}),
}

# Not delegable by a counselor, whatever the grantor holds.
NOT_DELEGABLE: Final = frozenset({P.STUDENTS_ASSIGN})

# Everything the owner may do with their own data.
OWNER_SET: Final = _STAFF - {
    P.NOTES_STAFF,
    P.TRANSCRIPTS_FULFIL,
    P.TRANSCRIPTS_OVERSEE,
    P.STUDENTS_ASSIGN,
    P.LABELS_OVERRIDE,
    P.ESTIMATES_VIEW_UNCALIBRATED,
    P.CATALOG_CURATE,
    P.AFFORDABILITY_SIGN_OFF,
    P.DOCUMENTS_REVIEW,
}


# Without the `admission_staff_view` consent staff see only name, class and the
# checklist status; no content permission survives.
NO_CONSENT_SET: Final = frozenset({P.TRANSCRIPTS_FULFIL, P.TRANSCRIPTS_OVERSEE})


class BuiltinRole:
    """A seeded sub-role: stable key, kind, names and permissions."""

    __slots__ = ("key", "kind", "names", "permissions")

    def __init__(
        self,
        key: str,
        kind: StaffKind,
        names: tuple[str, str, str],
        permissions: frozenset[Permission],
    ) -> None:
        """Store the definition; names are (uz, ru, en)."""
        self.key = key
        self.kind = kind
        self.names = names
        self.permissions = permissions


_READ_COMMENT_MENTOR: Final = frozenset(
    {
        P.PROFILE_READ,
        P.PROFILE_COMMENT,
        P.WORDS_READ,
        P.WORDS_COMMENT,
        P.ACTIVITIES_READ,
        P.ACTIVITIES_COMMENT,
        P.LIST_READ,
        P.LIST_COMMENT,
        P.ESSAYS_READ,
        P.ESSAYS_COMMENT,
    }
)

BUILTIN_ROLES: Final[tuple[BuiltinRole, ...]] = (
    BuiltinRole(
        "counselor_full",
        "counselor",
        ("Maslahatchi (toʼliq)", "Консультант (полный доступ)", "Counselor (full)"),
        KIND_ALLOW_LIST["counselor"],
    ),
    BuiltinRole(
        "counselor_documents",
        "counselor",
        ("Maslahatchi (hujjatlar)", "Консультант (документы)", "Counselor (documents)"),
        frozenset(
            {
                P.PROFILE_READ,
                P.LIST_READ,
                P.DOCUMENTS_READ,
                P.DOCUMENTS_ATTACH,
                P.DOCUMENTS_REVIEW,
                P.TRANSCRIPTS_OVERSEE,
                P.DEADLINES_MANAGE,
            }
        ),
    ),
    BuiltinRole(
        "student_counselor",
        "mentor",
        ("Talaba-maslahatchi", "Студент-консультант", "Student counselor"),
        _READ_COMMENT_MENTOR,
    ),
    BuiltinRole(
        "essay_mentor",
        "mentor",
        ("Insho boʼyicha mentor", "Ментор по эссе", "Essay mentor"),
        frozenset({P.WORDS_READ, P.ESSAYS_READ, P.ESSAYS_COMMENT}),
    ),
    BuiltinRole(
        "transcript_officer",
        "transcript_officer",
        ("Transkript masʼuli", "Ответственный за транскрипты", "Transcript officer"),
        frozenset({P.TRANSCRIPTS_FULFIL}),
    ),
)


def allowed_for_kind(kind: str, permissions: frozenset[Permission]) -> bool:
    """Return whether every permission is allowed for the sub-role kind."""
    allowed = KIND_ALLOW_LIST.get(kind)
    return allowed is not None and permissions <= allowed


def parse_permissions(values: list[str] | tuple[str, ...]) -> frozenset[Permission]:
    """Parse stored permission strings; unknown values are dropped."""
    known = {p.value for p in Permission}
    return frozenset(Permission(v) for v in values if v in known)
