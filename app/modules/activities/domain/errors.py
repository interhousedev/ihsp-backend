"""Errors of the activities module; code and message key derive from the class name."""

import re

from app.shared.base_error import (
    BaseError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ValidationFailedError,
)


class _Named:
    """Mixin: `FooBarError` gets code `activities/foo-bar`, key `activities-foo-bar`."""

    code: str
    message_key: str

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        if "code" not in cls.__dict__:
            slug = re.sub(r"(?<!^)(?=[A-Z])", "-", cls.__name__.removesuffix("Error"))
            cls.code = f"activities/{slug.lower()}"
            cls.message_key = f"activities-{slug.lower()}"


class Invalid(_Named, ValidationFailedError):
    """Input breaks a business rule (422)."""


class Conflict(_Named, ConflictError):
    """The state does not allow the action (409)."""


class Denied(_Named, ForbiddenError):
    """The caller lacks the right (403)."""


class Missing(_Named, NotFoundError):
    """The target does not exist or is hidden (404)."""


class BadRequest(_Named, BaseError):
    """The request itself is wrong (400)."""

    status = 400


class PermissionDeniedError(Denied):
    """The caller lacks the permission for this action."""


class ActivitiesNotFoundError(Missing):
    """Entity not found."""
