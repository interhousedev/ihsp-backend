"""Audit event types of the library (GEN-6).

`AuditDraft.type` is free text and the audit log has no list of allowed types; these
are the names the library and identity agree on, so a filter in the admin audit view
(`GET /v1/admin/audit?type=library.takedown`) finds what the code wrote.
"""

from enum import StrEnum


class LibraryAuditType(StrEnum):
    """Every librarian or administrator action in the library writes one of these."""

    APPROVE = "library.approve"
    REJECT = "library.reject"
    UNPUBLISH = "library.unpublish"
    TAKEDOWN = "library.takedown"
    SANCTION = "library.sanction"
    ROLE_GRANTED = "library.role_granted"
    HOLD = "library.hold"
    RESTORE = "library.restore"
    BOOK_PUBLISH = "library.book_publish"
    AUTO_APPROVE = "library.auto_approve"
