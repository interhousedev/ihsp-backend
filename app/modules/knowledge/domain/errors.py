"""Errors of the knowledge module."""

from app.shared.base_error import ConflictError, NotFoundError, ValidationFailedError


class KnowledgeEntryNotFoundError(NotFoundError):
    """The entry does not exist."""

    code = "knowledge_entry_not_found"
    message_key = "knowledge-not-found"


class KnowledgeKeyTakenError(ConflictError):
    """Another entry already has this key (keys ignore case)."""

    code = "knowledge_key_taken"
    message_key = "knowledge-key-taken"


class KnowledgeInvalidError(ValidationFailedError):
    """A field is empty or too long. Params: field."""

    code = "knowledge_invalid"
    message_key = "knowledge-invalid"
