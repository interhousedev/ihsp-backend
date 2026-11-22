"""Every admission column that references a user is handled by the erase."""

from app.modules.admission.infrastructure.personal_data import SPECS
from app.modules.admission.infrastructure.staff_repositories import (
    _USER_KEYED,
    _USER_NULLED,
    _student_tables,
)
from app.shared.db.base import Base

from sqlalchemy import Uuid

_USER_COLUMNS = {
    "user_id",
    "author_id",
    "created_by",
    "proposed_by",
    "submitted_by",
    "reporter_id",
    "uploaded_by",
    "attached_by",
    "granted_by",
    "reviewed_by",
    "hidden_by",
    "resolved_by",
    "signed_off_by",
    "updated_by",
    "reviewer_id",
    "superseded_by",
}

# Staff provenance on shared rows, or children deleted with a student-owned parent.
_ALLOWED = {
    ("catalog_proposals", "reviewed_by"),
    ("entitlements", "granted_by"),
    ("runtime_settings", "updated_by"),
    ("project_helpers", "created_by"),
    ("staff_roles", "created_by"),
    ("opportunity_submissions", "reviewed_by"),
    ("eligibility_rules", "reviewer_id"),
    ("facts", "reviewer_id"),
    ("opportunity_comments", "hidden_by"),
    ("staff_assignments", "granted_by"),
    ("opportunity_comment_reports", "resolved_by"),
    ("proof_claims", "superseded_by"),
    ("deadlines", "superseded_by"),
    ("affordability_checks", "signed_off_by"),
    ("document_versions", "uploaded_by"),
    ("document_attachments", "attached_by"),
    ("essay_versions", "created_by"),
}


def test_every_user_reference_is_erased_nulled_or_allowed() -> None:
    """A new user column fails here until the privacy erase covers it."""
    import app.bootstrap.common  # noqa: F401  (registers every ORM model)

    covered = {(t.name, c) for t, c in (*_USER_KEYED, *_USER_NULLED)}
    covered |= {(s.model.__tablename__, s.owner) for s in SPECS}
    students = {t.name for t in _student_tables()}
    missing = [
        (t.name, c.name)
        for t in Base.metadata.sorted_tables
        if t.schema == "admission" and t.name not in students
        for c in t.c
        if c.name in _USER_COLUMNS
        and isinstance(c.type, Uuid)
        and (t.name, c.name) not in covered | _ALLOWED
    ]
    assert missing == []
