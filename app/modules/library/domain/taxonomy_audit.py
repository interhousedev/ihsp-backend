"""Audit event types of topics, collections and reading lists (GEN-6).

Same naming as `app.shared.library_audit.LibraryAuditType`: `AuditDraft.type` is free
text, so a filter `GET /v1/admin/audit?type=library.topic_delete` finds these.
"""

from enum import StrEnum


class TaxonomyAuditType(StrEnum):
    """Librarian and Administration actions on the taxonomy."""

    SUBJECT_CREATE = "library.subject_create"
    SUBJECT_UPDATE = "library.subject_update"
    SUBJECT_DELETE = "library.subject_delete"
    TOPIC_CREATE = "library.topic_create"
    TOPIC_UPDATE = "library.topic_update"
    TOPIC_DELETE = "library.topic_delete"
    COLLECTION_CREATE = "library.collection_create"
    COLLECTION_UPDATE = "library.collection_update"
    COLLECTION_DELETE = "library.collection_delete"
    LIST_UPDATE = "library.list_update"
    LIST_DELETE = "library.list_delete"
