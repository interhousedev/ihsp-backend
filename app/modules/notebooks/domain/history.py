"""Chat history as the model sees it (§ 3.3.3)."""

import re
from collections.abc import Sequence

from app.modules.notebooks.domain.entities import NotebookMessage
from app.modules.notebooks.domain.enums import MessageRole
from app.modules.notebooks.domain.limits import HISTORY_MESSAGES

_CHIP = re.compile(r"⟦\s*(\d+(?:\s*,\s*\d+)*)\s*⟧")


def plain_citations(text: str) -> str:
    """Replace ``⟦1,2⟧`` with ``[1][2]``."""
    return _CHIP.sub(
        lambda match: "".join(f"[{n.strip()}]" for n in match.group(1).split(",")),
        text,
    )


def history_messages(
    messages: Sequence[NotebookMessage], limit: int = HISTORY_MESSAGES
) -> list[dict[str, str]]:
    """Return the last `limit` messages as ``{"role", "content"}`` for the model.

    Assistant citations ``⟦1,2⟧`` become ``[1][2]``; follow-up questions are not
    included; stopped answers are kept (the student saw them). Messages without text
    are skipped because providers reject empty content.

    Args:
        messages: The chat in order, oldest first.
        limit: How many of the latest messages to take.

    Returns:
        Role and content pairs, oldest first.
    """
    if limit <= 0:
        return []
    history: list[dict[str, str]] = []
    for message in messages[-limit:]:
        content = message.content.text.strip()
        if message.role is MessageRole.ASSISTANT:
            content = plain_citations(content)
        if content:
            history.append({"role": message.role.value, "content": content})
    return history
