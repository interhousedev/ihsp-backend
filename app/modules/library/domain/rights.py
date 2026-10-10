"""Rights of hosted books (LIB-3): public-domain dates, visibility, publish checklist.

Pure rules, no I/O. A book has a rights class and a recorded basis; the form will not
publish it without them, and `public` visibility is allowed only for the two free
classes (doc § 3.4).
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from uuid import UUID

from app.modules.library.domain.enums import Rights, TextStatus, Visibility
from app.modules.library.domain.errors import VisibilityConflictError

AUTHOR_TERM_YEARS = 70
"""Years of protection after the author's death."""

ANONYMOUS_TERM_YEARS = 50
"""Years of protection after the first publication of an anonymous work."""

FREE_FROM_THE_START = frozenset({"official_document", "folklore"})
"""Rules under which a work was never protected: no year is needed."""

CHECK_RIGHTS = "rights"
CHECK_TEXT_STATUS = "text_status"
CHECK_COVER = "cover"
CHECK_SUBJECTS = "subjects"

KEY_DEATH_YEAR = "rights_basis.author_death_year"
KEY_PUBLISHED_YEAR = "rights_basis.first_published_year"
KEY_RULE = "rights_basis.rule"
KEY_LICENCE = "licence"
KEY_SOURCE_URL = "rights_basis.source_url"
KEY_ATTRIBUTION = "rights_basis.attribution"
KEY_PROOF = "rights_proof_file_id"
KEY_SCOPE = "rights_basis.permission_scope"
KEY_EXPIRES = "rights_basis.permission_expires_on"
KEY_REFERENCE = "rights_basis.reference"

_FREE_VISIBILITIES = frozenset(Visibility)
_LYCEUM_VISIBILITIES = frozenset({Visibility.LYCEUM, Visibility.HIDDEN})


def public_domain_since(
    *, death_year: int | None = None, first_published_year: int | None = None
) -> int | None:
    """The first calendar year the work is free: 1 January of the returned year.

    A known author counts 70 full years from the 1 January after death (died 1955:
    free from 1 January 2026). An anonymous work counts 50 years from the 1 January
    after the first publication. None when neither year is known.
    """
    if death_year is not None:
        return death_year + AUTHOR_TERM_YEARS + 1
    if first_published_year is not None:
        return first_published_year + ANONYMOUS_TERM_YEARS + 1
    return None


def allowed_visibilities(rights: Rights) -> frozenset[Visibility]:
    """Visibilities a book of this rights class may have."""
    if rights in (Rights.PUBLIC_DOMAIN, Rights.OPEN_LICENSE):
        return _FREE_VISIBILITIES
    return _LYCEUM_VISIBILITIES


def check_visibility(rights: Rights, visibility: Visibility) -> None:
    """Raise `library/visibility-conflict` when the class forbids the visibility."""
    if visibility not in allowed_visibilities(rights):
        raise VisibilityConflictError(
            params={"rights": rights.value, "visibility": visibility.value},
            support_details=f"{visibility.value} is not allowed for {rights.value}",
        )


def _has(basis: Mapping[str, object], key: str) -> bool:
    value = basis.get(key)
    return value is not None and value != ""


def _year(basis: Mapping[str, object], key: str) -> int | None:
    value = basis.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _public_domain_missing(basis: Mapping[str, object], today: date) -> list[str]:
    missing: list[str] = []
    rule = str(basis.get("rule") or "")
    death = _year(basis, "author_death_year")
    published = _year(basis, "first_published_year")
    if rule not in FREE_FROM_THE_START:
        free_since = public_domain_since(
            death_year=death, first_published_year=published
        )
        if free_since is None or free_since > today.year:
            key = KEY_PUBLISHED_YEAR if death is None and published else KEY_DEATH_YEAR
            missing.append(key)
    if not rule:
        missing.append(KEY_RULE)
    return missing


def _permission_missing(
    basis: Mapping[str, object], proof_file_id: UUID | str | None, today: date
) -> list[str]:
    missing: list[str] = []
    if not proof_file_id:
        missing.append(KEY_PROOF)
    if not _has(basis, "permission_scope"):
        missing.append(KEY_SCOPE)
    if not _expiry_in_future(basis.get("permission_expires_on"), today):
        missing.append(KEY_EXPIRES)
    return missing


def _expiry_in_future(value: object, today: date) -> bool:
    if not isinstance(value, str) or not value:
        return False
    try:
        return date.fromisoformat(value) >= today
    except ValueError:
        return False


def rights_missing(
    rights: Rights,
    basis: Mapping[str, object],
    *,
    licence: str | None = None,
    proof_file_id: UUID | str | None = None,
    today: date,
) -> list[str]:
    """Fields of the rights panel that are missing or invalid; empty means complete.

    Names are the field paths the form uses (`rights_basis.source_url`, `licence`).
    """
    if rights is Rights.PUBLIC_DOMAIN:
        return _public_domain_missing(basis, today)
    if rights is Rights.OPEN_LICENSE:
        missing = [] if licence else [KEY_LICENCE]
        if not _has(basis, "source_url"):
            missing.append(KEY_SOURCE_URL)
        if not _has(basis, "attribution"):
            missing.append(KEY_ATTRIBUTION)
        return missing
    if rights is Rights.PERMISSION:
        return _permission_missing(basis, proof_file_id, today)
    return [] if _has(basis, "reference") else [KEY_REFERENCE]


@dataclass(frozen=True, slots=True)
class ChecklistFacts:
    """What the publish checklist looks at (gathered by the use case)."""

    rights: Rights
    rights_basis: Mapping[str, object]
    licence: str | None
    proof_file_id: UUID | str | None
    primary_text_status: TextStatus | None
    primary_is_pdf: bool
    has_cover: bool
    subject_count: int
    collection_count: int


@dataclass(frozen=True, slots=True)
class ChecklistEntry:
    """One line of the checklist: `rights`, `text_status`, `cover`, `subjects`."""

    key: str
    ok: bool


def publish_checklist(facts: ChecklistFacts, *, today: date) -> list[ChecklistEntry]:
    """The four checks before a book is published (doc § 3.4)."""
    del today
    text_ok = facts.primary_text_status in (TextStatus.READY, TextStatus.NO_TEXT)
    return [
        ChecklistEntry(CHECK_TEXT_STATUS, text_ok),
        ChecklistEntry(CHECK_COVER, facts.has_cover or facts.primary_is_pdf),
        ChecklistEntry(
            CHECK_SUBJECTS, facts.subject_count > 0 or facts.collection_count > 0
        ),
    ]


def publish_missing(facts: ChecklistFacts, *, today: date) -> list[str]:
    """`params.missing[]` of `library/rights-incomplete`.

    A failed rights check is expanded into the rights fields that are missing; the
    other checks appear under their own key.
    """
    missing: list[str] = []
    for entry in publish_checklist(facts, today=today):
        if entry.ok:
            continue
        if entry.key == CHECK_RIGHTS:
            missing.extend(
                rights_missing(
                    facts.rights,
                    facts.rights_basis,
                    licence=facts.licence,
                    proof_file_id=facts.proof_file_id,
                    today=today,
                )
            )
        else:
            missing.append(entry.key)
    return missing
