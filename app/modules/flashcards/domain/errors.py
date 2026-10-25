"""Errors of the flashcards module."""

from app.shared.base_error import NotFoundError, ValidationFailedError


class FlashcardSetNotFoundError(NotFoundError):
    """The set does not exist or belongs to someone else."""

    code = "flashcards/set-not-found"
    message_key = "fc-set-not-found"


class CardNotFoundError(NotFoundError):
    """The card does not exist or its set belongs to someone else."""

    code = "flashcards/card-not-found"
    message_key = "fc-card-not-found"


class InvalidCardsError(ValidationFailedError):
    """Too many cards, or a card side that is empty or too long.

    Params: reason (`count` or `text`), max_cards, max_chars.
    """

    code = "flashcards/invalid-cards"
    message_key = "fc-invalid-cards"


class InvalidSetError(ValidationFailedError):
    """A set field is out of range.

    Params: field (`title`, `description`, `new_per_day`, `reviews_per_day`),
    min, max.
    """

    code = "flashcards/invalid-set"
    message_key = "fc-invalid-set"


class ShareNotFoundError(NotFoundError):
    """The share does not exist, is not active or is not a flash card set."""

    code = "flashcards/share-not-found"
    message_key = "fc-share-not-found"
