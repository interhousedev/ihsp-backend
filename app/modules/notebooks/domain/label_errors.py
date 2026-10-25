"""Errors of the topic labels; `code` is the problem+json `type`."""

from app.shared.base_error import ConflictError, NotFoundError, ValidationFailedError


class LabelsLimitError(ConflictError):
    """12 labels in the notebook, or more than 3 labels on one source."""

    code = "notebooks/labels-limit"
    message_key = "notebooks-labels-limit"


class LabelNotFoundError(NotFoundError):
    """The label is missing or belongs to another notebook."""

    code = "notebooks/label-not-found"
    message_key = "notebooks-label-not-found"


class LabelDuplicateError(ConflictError):
    """The notebook already has a label with that name (any case)."""

    code = "notebooks/label-duplicate"
    message_key = "notebooks-label-duplicate"


class LabelsNothingToLabelError(ValidationFailedError):
    """Auto labels without any selected, ready source."""

    code = "notebooks/labels-nothing-to-label"
    message_key = "notebooks-labels-nothing-to-label"


class LabelsRunningError(ConflictError):
    """The automatic labeling of this notebook is already running."""

    code = "notebooks/labels-running"
    message_key = "notebooks-labels-running"
