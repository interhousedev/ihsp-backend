"""Shared pieces of the course author tools: scope, collaborators, errors, shapes.

The course and the workspace notebook of every author tool come from the chat's
scope (`ToolContext.scope`), never from the model's arguments; a step id from the
model is accepted only when the LMS says it belongs to the scope's course.
"""

from collections.abc import Awaitable
from typing import Any, TypeVar
from uuid import UUID

from app.modules.ai.application.late_bindings import LateBindings
from app.modules.ai.application.tools.base import ToolContext
from app.modules.ai.domain.chat_scope import ChatScope
from app.modules.ai.domain.errors import ToolArgumentsError, ToolFailedError
from app.shared.base_error import BaseError
from app.shared.contracts.lms import (
    LmsDraftCommands,
    LmsQueries,
    LmsWorkspace,
    LmsWorkspaceCommands,
)
from app.shared.contracts.lms_blocks import BlockInputError
from app.shared.contracts.notebooks import NotebooksCommands, NotebooksQueries

T = TypeVar("T")

UNAVAILABLE = "the course tools are not available here; tell the teacher"
CONFLICT = (
    "draft-conflict: the step changed after you read it{current}. Call "
    "get_step_draft once, apply your change to the fresh content and its "
    "lock_version, and retry once; if it fails again, stop and ask the teacher."
)
PERMISSION = (
    "permission: the teacher may not edit this course (any more). Stop and tell "
    "the teacher; do not retry."
)
STEP_FOREIGN = (
    "step not found in this course: use a step id from the course outline "
    "(get_course_outline)"
)


def scope_of(ctx: ToolContext) -> ChatScope:
    """Return the course workspace of the chat or fail (only author chats have one)."""
    if ctx.scope is None:
        raise ToolFailedError(support_details="this chat has no course")
    return ctx.scope


def _bound(value: T | None) -> T:
    if value is None:
        raise ToolFailedError(support_details=UNAVAILABLE)
    return value


def workspace_of(bindings: LateBindings) -> LmsWorkspace:
    """Return the LMS workspace contract or fail like a tool."""
    return _bound(bindings.lms_workspace)


def workspace_commands_of(bindings: LateBindings) -> LmsWorkspaceCommands:
    """Return the LMS workspace writes or fail like a tool."""
    return _bound(bindings.lms_workspace_commands)


def lms_queries_of(bindings: LateBindings) -> LmsQueries:
    """Return the LMS author reads or fail like a tool."""
    return _bound(bindings.lms_queries)


def draft_commands_of(bindings: LateBindings) -> LmsDraftCommands:
    """Return the add-only LMS draft writes or fail like a tool."""
    return _bound(bindings.lms_draft_commands)


def notebook_queries_of(bindings: LateBindings) -> NotebooksQueries:
    """Return the notebooks reads or fail like a tool."""
    return _bound(bindings.notebooks)


def notebook_commands_of(bindings: LateBindings) -> NotebooksCommands:
    """Return the notebooks writes or fail like a tool."""
    return _bound(bindings.notebooks_commands)


def failure(exc: BaseError) -> ToolFailedError:
    """Turn an error of the LMS or notebooks into a short message the model acts on."""
    if exc.status == 409:
        version = exc.params.get("lock_version")
        current = f" (current lock_version {version})" if version is not None else ""
        return ToolFailedError(support_details=CONFLICT.format(current=current))
    if exc.status == 403:
        return ToolFailedError(support_details=PERMISSION)
    if exc.status == 404:
        return ToolFailedError(
            support_details=f"not-found ({exc.code}): check the ids with "
            "get_course_outline or list_workspace_outputs"
        )
    if exc.status == 422:
        kind = "content-invalid" if exc.code == "lms/content-invalid" else "invalid"
        return ToolFailedError(
            support_details=f"{kind} ({exc.code}): {_details(exc)}. Fix exactly "
            "this and retry once."
        )
    if exc.status == 429:
        return ToolFailedError(
            support_details=f"limit ({exc.code}): {_details(exc)}. Tell the "
            "teacher; do not retry now."
        )
    return ToolFailedError(support_details=f"{exc.code}: {exc.support_details}")


def _details(exc: BaseError) -> str:
    errors = exc.params.get("errors")
    if isinstance(errors, list) and errors:
        return "; ".join(_one_error(e) for e in errors[:5])
    for key in ("reason", "details", "problems"):
        if exc.params.get(key):
            return str(exc.params[key])
    return exc.support_details


def _one_error(error: Any) -> str:
    if not isinstance(error, dict):
        return str(error)
    loc = ".".join(str(p) for p in error.get("loc", []))
    return f"{loc}: {error.get('msg', '')}" if loc else str(error.get("msg", ""))


async def lms_call(call: Awaitable[T]) -> T:
    """Await an LMS or notebooks call; its errors become actionable tool failures."""
    try:
        return await call
    except (ToolFailedError, ToolArgumentsError):
        raise
    except BaseError as exc:
        raise failure(exc) from exc


def block_rule(error: BlockInputError, where: str) -> ToolArgumentsError:
    """Return the argument error for a block that breaks a rule of its type."""
    text = f"{where}: {error}"
    return ToolArgumentsError(params={"details": text}, support_details=text)


async def course_step(
    bindings: LateBindings, ctx: ToolContext, step_id: UUID
) -> dict[str, Any]:
    """Return the step's draft if the step belongs to the chat's course, else fail."""
    scope = scope_of(ctx)
    draft = await lms_call(lms_queries_of(bindings).step_draft(step_id, ctx.actor))
    if str(draft.get("course_id")) != str(scope.course_id):
        raise ToolFailedError(support_details=STEP_FOREIGN)
    return draft


def step_title(draft: dict[str, Any]) -> str:
    """Return the title of a step draft (``content.title``)."""
    content = draft.get("content") or {}
    return str(content.get("title") or draft.get("title") or "")


def draft_blocks(draft: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the blocks of a step draft (``content.blocks``)."""
    content = draft.get("content") or {}
    blocks = content.get("blocks") or []
    return [b for b in blocks if isinstance(b, dict)]


def first_lines(markdown: str, lines: int = 6, chars: int = 400) -> list[str]:
    """Return the first non-empty lines of Markdown for an approval card."""
    found = [line.strip() for line in markdown.splitlines() if line.strip()]
    shown: list[str] = []
    used = 0
    for line in found[:lines]:
        cut = line[: max(chars - used, 0)]
        if not cut:
            break
        shown.append(cut)
        used += len(cut)
    if len(found) > len(shown):
        shown.append("…")
    return shown
