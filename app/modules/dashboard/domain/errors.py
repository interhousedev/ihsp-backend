"""Errors of the dashboard module."""

from app.shared.base_error import ConflictError, ValidationFailedError


class LayoutVersionConflictError(ConflictError):
    """The layout was saved elsewhere since the client read it."""

    code = "dashboard/version-conflict"
    message_key = "dashboard-version-conflict"


class InvalidLayoutError(ValidationFailedError):
    """Too many widgets or repeated widget ids. Params: max."""

    code = "dashboard/invalid-layout"
    message_key = "dashboard-invalid-layout"
