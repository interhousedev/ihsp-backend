"""Which model calls keep their text in Langfuse: the one masking decision.

A masked trace keeps the task, model, user, session, surface, tokens, cost, latency
and status; its input and output become `REDACTED` and its error a fixed code.

- Essays and other private writing are always masked: every task declared
  `private_content` (all admission tasks: essay review, coach, deep read, practice,
  app review, exemplars...), the Studio essay feedback and the teacher checks of a
  student's work, and any call made from the admission surface (its embeddings).
- A user who turned on `limit_ai_tracing` keeps the text of the general assistant
  chat on the web and in Telegram only; every other call of theirs is masked.
"""

from typing import Final

from app.shared.ai_tasks import TASK_SPECS, AiTask
from app.shared.usage_context import SURFACE_ADMISSION, SURFACE_TELEGRAM, SURFACE_WEB

REDACTED: Final = "[redacted]"
"""What a masked trace shows instead of a prompt or an answer."""

ALWAYS_MASKED: Final[frozenset[str]] = frozenset(
    {task.value for task, spec in TASK_SPECS.items() if spec.private_content}
    | {
        AiTask.EXERCISE_FEEDBACK.value,  # a student's essay or free response
        AiTask.TEACHER_WORK_CHECK.value,  # a student's work
        AiTask.TEACHER_AI_CHECK.value,  # a student's text
    }
)
"""Tasks that carry essays or other private writing: never sent as text."""

OPEN_CHAT_TASKS: Final[frozenset[str]] = frozenset(
    {
        AiTask.STUDENT_CHAT.value,
        AiTask.STUDENT_CHAT_SMART.value,
        AiTask.ADMIN_CHAT.value,
        AiTask.GUEST_CHAT.value,
    }
)
"""The general assistant chat: kept as text even for a user who limits tracing."""

OPEN_SURFACES: Final[frozenset[str]] = frozenset({SURFACE_WEB, SURFACE_TELEGRAM})


def masks_content(
    task: str | None, surface: str | None, *, limit_tracing: bool
) -> bool:
    """True when the call's prompt and answer must not reach Langfuse."""
    if surface == SURFACE_ADMISSION or (task is not None and task in ALWAYS_MASKED):
        return True
    if not limit_tracing:
        return False
    return not (surface in OPEN_SURFACES and task in OPEN_CHAT_TASKS)
