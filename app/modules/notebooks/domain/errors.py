"""Errors of the notebooks module (§ 4.7); `code` is the problem+json `type`."""

from app.shared.base_error import (
    BaseError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
    RateLimitedError,
    ValidationFailedError,
)


class NotebookNotFoundError(NotFoundError):
    """Notebook, source, passage or output is missing or is not the caller's."""

    code = "notebooks/not-found"
    message_key = "notebooks-not-found"


class NotebookLimitError(ConflictError):
    """The student already has the maximum number of notebooks."""

    code = "notebooks/notebook-limit"
    message_key = "notebooks-notebook-limit"


class AutoNotebookReadOnlyError(ConflictError):
    """Adding or removing lesson sources by hand in a notebook the system keeps."""

    code = "notebooks/auto-readonly"
    message_key = "notebooks-auto-readonly"


class WorkspaceReadOnlyError(ForbiddenError):
    """A course member who may only read (``view_drafts``) tried to change it."""

    code = "notebooks/workspace-readonly"
    message_key = "notebooks-workspace-readonly"


class WorkspaceActionError(ConflictError):
    """The action does not exist for a course workspace (delete, copy, ...)."""

    code = "notebooks/workspace-action"
    message_key = "notebooks-workspace-action"


class AutoNotebookLimitError(ConflictError):
    """The student already has the maximum number of subject and lesson notebooks."""

    code = "notebooks/auto-limit"
    message_key = "notebooks-auto-limit"


class SourceLimitError(ConflictError):
    """The notebook has the maximum number of sources or the text cap is reached."""

    code = "notebooks/source-limit"
    message_key = "notebooks-source-limit"


class SourceDuplicateError(ConflictError):
    """The same file, chat, step, set or page is already a source."""

    code = "notebooks/source-duplicate"
    message_key = "notebooks-source-duplicate"


class SourceForbiddenError(ForbiddenError):
    """Not the caller's file, chat or set; not enrolled; not in the audience."""

    code = "notebooks/source-forbidden"
    message_key = "notebooks-source-forbidden"


class SourceUnsupportedError(ValidationFailedError):
    """No text extraction for that file type, or a kind that is not available yet."""

    code = "notebooks/source-unsupported"
    message_key = "notebooks-source-unsupported"


class SourceTooLargeError(BaseError):
    """The text is longer than the per-source cap."""

    code = "notebooks/source-too-large"
    status = 413
    message_key = "notebooks-source-too-large"


class SourceNotReadyError(ConflictError):
    """Editing or syncing a source that is still processing."""

    code = "notebooks/source-not-ready"
    message_key = "notebooks-source-not-ready"


class NoSourcesSelectedError(ValidationFailedError):
    """Chat or output without any ready, selected source."""

    code = "notebooks/no-sources-selected"
    message_key = "notebooks-no-sources-selected"


class QuotaExceededError(RateLimitedError):
    """The daily count of one kind of output is used up (kind, limit, resets_at)."""

    code = "notebooks/quota-exceeded"
    message_key = "notebooks-quota-exceeded"


class LimitReachedError(RateLimitedError):
    """The weighted-token budget is used up (params: scope, resets_at)."""

    code = "notebooks/limit-reached"
    message_key = "notebooks-limit-reached"


class BusyError(ConflictError):
    """Three outputs are already generating, or a question is already running."""

    code = "notebooks/busy"
    message_key = "notebooks-busy"


class ArtifactLimitError(ConflictError):
    """The notebook already holds the maximum number of outputs."""

    code = "notebooks/artifact-limit"
    message_key = "notebooks-artifact-limit"


class ArtifactNotReadyError(ConflictError):
    """Content, progress or an action on an output that is not ready."""

    code = "notebooks/artifact-not-ready"
    message_key = "notebooks-artifact-not-ready"


class InvalidOptionsError(ValidationFailedError):
    """The options do not match the kind of output."""

    code = "notebooks/invalid-options"
    message_key = "notebooks-invalid-options"


class FeatureDisabledError(NotFoundError):
    """The feature (audio overview, notebooks) is switched off."""

    code = "notebooks/feature-disabled"
    message_key = "notebooks-feature-disabled"


class SourceReadError(BaseError):
    """Internal: a reader could not produce text; `failure` is the machine code."""

    code = "notebooks/source-read-failed"
    status = 422
    message_key = "notebooks-source-read-failed"

    def __init__(self, failure: str, *, support_details: str | None = None) -> None:
        """Keep the failure code (a `SourceFailure` value)."""
        super().__init__(params={"failure": failure}, support_details=support_details)
        self.failure = failure


class SourceUnavailableError(SourceReadError):
    """Internal: the object behind the source cannot be used now (but may again).

    The source becomes `unavailable` instead of `failed`, and a later sync reads it
    again (a library book that was held and then restored).
    """

    code = "notebooks/source-unavailable"


class LibraryNotSupportedError(ConflictError):
    """A UniLibrary record cannot be a source (the library's own problem type)."""

    code = "library/not-supported"
    message_key = "library-not-supported"


class OutputInvalidError(BaseError):
    """Internal: the model's JSON broke a rule; `problems` feed the repair call."""

    code = "notebooks/output-invalid"
    status = 422
    message_key = "notebooks-output-invalid"

    def __init__(self, problems: list[str]) -> None:
        """Keep the list of problems for the repair call."""
        super().__init__(support_details="; ".join(problems)[:500])
        self.problems = problems
