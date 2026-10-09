"""Errors of topics, collections, reading lists and statistics (doc § 7.4).

Not-found errors of the same families (`TopicNotFoundError`, `CollectionNotFoundError`,
`ListNotFoundError`, `ListTooLongError`) live in `domain/errors.py`.
"""

from app.shared.base_error import (
    ConflictError,
    ForbiddenError,
    ValidationFailedError,
)


class NameRequiredError(ValidationFailedError):
    """A topic or a collection has no name in any language."""

    code = "library/name-required"
    message_key = "library-name-required"


class SlugInvalidError(ValidationFailedError):
    """A slug is not lowercase Latin words joined by hyphens."""

    code = "library/slug-invalid"
    message_key = "library-slug-invalid"


class TopicSlugTakenError(ConflictError):
    """Another topic with the same parent already has this slug."""

    code = "library/topic-slug-taken"
    message_key = "library-topic-slug-taken"


class TopicParentInvalidError(ValidationFailedError):
    """The parent is missing, of another subject, or the topic itself or its child."""

    code = "library/topic-parent-invalid"
    message_key = "library-topic-parent-invalid"


class TopicSubjectFixedError(ValidationFailedError):
    """A topic cannot move to another subject."""

    code = "library/topic-subject-fixed"
    message_key = "library-topic-subject-fixed"


class UnknownSubjectError(ValidationFailedError):
    """The subject id does not exist (`params.subject_id`)."""

    code = "library/unknown-subject"
    message_key = "library-unknown-subject"


class CoverInvalidError(ValidationFailedError):
    """The cover is not a stored library cover file."""

    code = "library/cover-invalid"
    message_key = "library-cover-invalid"


class CollectionTooLongError(ValidationFailedError):
    """More items than a collection may hold (`params.max`)."""

    code = "library/collection-too-long"
    message_key = "library-collection-too-long"


class ListForbiddenError(ForbiddenError):
    """The caller sees the list but may not change it, or not for this audience."""

    code = "library/list-forbidden"
    message_key = "library-list-forbidden"


class ListInvalidError(ValidationFailedError):
    """A reading list field breaks a rule (`params.field`)."""

    code = "library/list-invalid"
    message_key = "library-list-invalid"


class ListEntryInvalidError(ValidationFailedError):
    """An entry breaks a rule (`params.position`, `params.reason`)."""

    code = "library/list-entry-invalid"
    message_key = "library-list-entry-invalid"


class StatsRangeError(ValidationFailedError):
    """The statistics window is inverted or longer than a year."""

    code = "library/stats-range-invalid"
    message_key = "library-stats-range-invalid"
