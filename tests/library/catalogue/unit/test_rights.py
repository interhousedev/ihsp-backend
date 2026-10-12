"""LIB-3: public-domain dates, rights/visibility consistency, publish checklist."""

from datetime import date

from app.modules.library.domain.enums import Rights, TextStatus, Visibility
from app.modules.library.domain.rights import (
    ChecklistFacts,
    allowed_visibilities,
    public_domain_since,
    publish_checklist,
    publish_missing,
    rights_missing,
)

import pytest

TODAY = date(2026, 10, 6)


def test_author_who_died_in_1955_is_free_from_1_january_2026() -> None:
    """LIB-3: 70 years counted from the 1 January after death."""
    assert public_domain_since(death_year=1955) == 2026


def test_anonymous_work_is_free_fifty_years_after_first_publication() -> None:
    """LIB-3: 50 full years from 1 January after the first publication."""
    assert public_domain_since(first_published_year=1970) == 2021


def test_death_year_wins_over_publication_year() -> None:
    """LIB-3: a known author is measured by death, not by publication."""
    assert public_domain_since(death_year=1990, first_published_year=1950) == 2061


def test_no_year_gives_no_date() -> None:
    """LIB-3: without a basis there is no public-domain date."""
    assert public_domain_since() is None


@pytest.mark.parametrize("rights", [Rights.PUBLIC_DOMAIN, Rights.OPEN_LICENSE])
@pytest.mark.parametrize("visibility", list(Visibility))
def test_free_works_may_have_any_visibility(
    rights: Rights, visibility: Visibility
) -> None:
    """LIB-3: public domain and open licences may be public or lyceum-only."""
    assert visibility in allowed_visibilities(rights)


@pytest.mark.parametrize("rights", [Rights.PERMISSION, Rights.OFFICIAL])
def test_permission_and_official_books_are_never_public(rights: Rights) -> None:
    """LIB-3: hosted by permission or on an official basis means lyceum only."""
    assert Visibility.PUBLIC not in allowed_visibilities(rights)
    assert Visibility.LYCEUM in allowed_visibilities(rights)


def test_public_domain_with_old_death_year_is_complete() -> None:
    """LIB-3: a recorded death year long enough ago and a rule is a full basis."""
    missing = rights_missing(
        Rights.PUBLIC_DOMAIN,
        {"author_death_year": 1938, "rule": "life+70"},
        today=TODAY,
    )

    assert missing == []


def test_public_domain_refuses_a_death_year_that_is_too_recent() -> None:
    """LIB-3: the form refuses earlier dates than the computed one."""
    missing = rights_missing(
        Rights.PUBLIC_DOMAIN,
        {"author_death_year": 1990, "rule": "life+70"},
        today=TODAY,
    )

    assert missing == ["rights_basis.author_death_year"]


def test_public_domain_without_year_or_rule_lists_both() -> None:
    """LIB-3: nothing recorded means both fields are missing."""
    missing = rights_missing(Rights.PUBLIC_DOMAIN, {}, today=TODAY)

    assert missing == ["rights_basis.author_death_year", "rights_basis.rule"]


@pytest.mark.parametrize("rule", ["official_document", "folklore"])
def test_official_documents_and_folklore_need_only_the_rule(rule: str) -> None:
    """LIB-3: these classes are free from the start, no year needed."""
    assert rights_missing(Rights.PUBLIC_DOMAIN, {"rule": rule}, today=TODAY) == []


def test_anonymous_work_published_long_ago_is_complete() -> None:
    """LIB-3: first publication more than 50 years ago is enough."""
    basis = {"first_published_year": 1960, "rule": "anonymous+50"}

    assert rights_missing(Rights.PUBLIC_DOMAIN, basis, today=TODAY) == []


def test_open_license_needs_licence_source_and_attribution() -> None:
    """LIB-3: licence code, link to the statement and attribution text."""
    missing = rights_missing(Rights.OPEN_LICENSE, {}, today=TODAY)

    assert missing == [
        "licence",
        "rights_basis.source_url",
        "rights_basis.attribution",
    ]


def test_open_license_with_everything_is_complete() -> None:
    """LIB-3: the three pieces make the basis complete."""
    basis = {"source_url": "https://cc.example/by", "attribution": "A. Author"}

    assert (
        rights_missing(Rights.OPEN_LICENSE, basis, licence="CC BY", today=TODAY) == []
    )


def test_permission_needs_proof_scope_and_a_future_expiry() -> None:
    """LIB-3: the scan of the permission, its scope and expiry."""
    missing = rights_missing(Rights.PERMISSION, {}, today=TODAY)

    assert missing == [
        "rights_proof_file_id",
        "rights_basis.permission_scope",
        "rights_basis.permission_expires_on",
    ]


def test_expired_permission_is_not_a_basis() -> None:
    """LIB-3: a permission that ended cannot be published."""
    basis = {"permission_scope": "lyceum", "permission_expires_on": "2026-09-30"}

    missing = rights_missing(Rights.PERMISSION, basis, proof_file_id="f", today=TODAY)

    assert missing == ["rights_basis.permission_expires_on"]


def test_valid_permission_is_complete() -> None:
    """LIB-3: proof, scope and a date in the future."""
    basis = {"permission_scope": "lyceum", "permission_expires_on": "2027-01-31"}

    assert (
        rights_missing(Rights.PERMISSION, basis, proof_file_id="f", today=TODAY) == []
    )


def test_official_books_need_a_reference() -> None:
    """LIB-3: the order or the publisher's permission."""
    assert rights_missing(Rights.OFFICIAL, {}, today=TODAY) == [
        "rights_basis.reference"
    ]
    assert (
        rights_missing(Rights.OFFICIAL, {"reference": "Order 12/2024"}, today=TODAY)
        == []
    )


def _facts(
    *,
    rights_basis: dict[str, object] | None = None,
    primary_text_status: TextStatus | None = TextStatus.READY,
    primary_is_pdf: bool = True,
    has_cover: bool = True,
    subject_count: int = 1,
    collection_count: int = 0,
) -> ChecklistFacts:
    return ChecklistFacts(
        rights=Rights.OFFICIAL,
        rights_basis=(
            {"reference": "Order 12"} if rights_basis is None else rights_basis
        ),
        licence=None,
        proof_file_id=None,
        primary_text_status=primary_text_status,
        primary_is_pdf=primary_is_pdf,
        has_cover=has_cover,
        subject_count=subject_count,
        collection_count=collection_count,
    )


def test_complete_book_has_an_all_green_checklist() -> None:
    """LIB-3: rights, text status, cover and subjects all ok."""
    checklist = publish_checklist(_facts(), today=TODAY)

    assert [(entry.key, entry.ok) for entry in checklist] == [
        ("text_status", True),
        ("cover", True),
        ("subjects", True),
    ]
    assert publish_missing(_facts(), today=TODAY) == []


def test_unknown_text_status_blocks_publishing() -> None:
    """LIB-3: text status must be ready or no_text, not pending."""
    facts = _facts(primary_text_status=TextStatus.PENDING)

    assert publish_missing(facts, today=TODAY) == ["text_status"]


def test_scan_without_text_is_a_known_status() -> None:
    """LIB-3: `no_text` is fine; such a book is just not searchable."""
    facts = _facts(primary_text_status=TextStatus.NO_TEXT)

    assert publish_missing(facts, today=TODAY) == []


def test_book_without_a_file_has_no_text_status() -> None:
    """LIB-3: no file at all fails the text status check."""
    facts = _facts(primary_text_status=None, primary_is_pdf=False)

    assert "text_status" in publish_missing(facts, today=TODAY)


def test_pdf_without_cover_is_fine_because_page_one_can_be_rendered() -> None:
    """LIB-3: cover present or page 1 renderable."""
    facts = _facts(has_cover=False, primary_is_pdf=True)

    assert publish_missing(facts, today=TODAY) == []


def test_epub_without_cover_fails_the_cover_check() -> None:
    """LIB-3: only a PDF has a page 1 that can be shown as the cover."""
    facts = _facts(has_cover=False, primary_is_pdf=False)

    assert publish_missing(facts, today=TODAY) == ["cover"]


def test_collection_alone_satisfies_the_subject_rule() -> None:
    """LIB-3: at least one subject or collection."""
    facts = _facts(subject_count=0, collection_count=1)

    assert publish_missing(facts, today=TODAY) == []
    assert publish_missing(_facts(subject_count=0), today=TODAY) == ["subjects"]


def test_missing_rights_fields_are_listed_instead_of_the_rights_key() -> None:
    """LIB-3: `params.missing[]` names the fields, as the web contract expects."""
    facts = _facts(rights_basis={}, primary_text_status=TextStatus.PENDING)

    assert publish_missing(facts, today=TODAY) == ["text_status"]
