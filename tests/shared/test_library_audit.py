"""GEN-6, LIB-1: the audit event types of the library."""

from app.modules.identity.domain.audit_event import LIBRARY_ROLE_GRANTED
from app.shared.library_audit import LibraryAuditType


def test_the_library_audit_types_are_the_agreed_names() -> None:
    """GEN-6: ten `library.*` types, a stable list for audit filters."""
    assert {kind.value for kind in LibraryAuditType} == {
        "library.approve",
        "library.reject",
        "library.unpublish",
        "library.takedown",
        "library.sanction",
        "library.role_granted",
        "library.hold",
        "library.restore",
        "library.book_publish",
        "library.auto_approve",
    }


def test_identity_writes_the_role_grant_under_the_library_name() -> None:
    """LIB-1: granting `librarian` is `library.role_granted`."""
    assert (
        LIBRARY_ROLE_GRANTED == LibraryAuditType.ROLE_GRANTED == "library.role_granted"
    )
