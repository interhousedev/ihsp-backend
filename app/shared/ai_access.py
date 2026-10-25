"""Administration can revoke AI access per user, per scope.

Two scopes: ``chat`` (assistants: web chat, Telegram bot, MCP tools, course author) and
``notebooks`` (notebook chat and Studio outputs). Every model task belongs to exactly
one scope, so a revoked user is refused at the model call whichever way it was reached.
"""

from dataclasses import dataclass
from typing import Final, Literal

from app.shared.ai_tasks import NOTEBOOK_TASKS, AiTask

AiScope = Literal["chat", "notebooks"]

AI_TASK_SCOPE: Final[dict[AiTask, AiScope]] = {
    task: (
        "notebooks"
        if task in NOTEBOOK_TASKS or task is AiTask.CONTEXT_COMPACT
        else "chat"
    )
    for task in AiTask
}
"""The scope of every model task (exhaustive: a new task must be placed here)."""


def scope_of(task: str | None) -> AiScope:
    """The scope of a task name from the usage ledger; no task counts as chat."""
    if task is None:
        return "chat"
    try:
        return AI_TASK_SCOPE[AiTask(task)]
    except ValueError:
        return "chat"


@dataclass(frozen=True, slots=True)
class AiAccess:
    """What Administration revoked from one user (False everywhere by default)."""

    chat_blocked: bool = False
    notebooks_blocked: bool = False

    def blocks(self, scope: AiScope) -> bool:
        """True when the given scope is revoked."""
        return self.chat_blocked if scope == "chat" else self.notebooks_blocked
