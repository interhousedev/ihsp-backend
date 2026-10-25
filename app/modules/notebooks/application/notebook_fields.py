"""Checks of the fields a student edits on a notebook (title, emoji, chat)."""

from collections.abc import Mapping

from app.modules.notebooks.domain.entities import ChatConfig
from app.modules.notebooks.domain.errors import InvalidOptionsError
from app.modules.notebooks.domain.limits import (
    EMOJI_MAX_CHARS,
    NOTEBOOK_TITLE_MAX_CHARS,
)

from pydantic import ValidationError


def invalid(field: str) -> InvalidOptionsError:
    """The error for a field that is unknown or has a value that is not allowed."""
    return InvalidOptionsError(params={"field": field})


def clean_title(value: object) -> str:
    """Return the trimmed title (1 to 120 characters) or raise `InvalidOptionsError`."""
    if not isinstance(value, str):
        raise invalid("title")
    title = value.strip()
    if not 1 <= len(title) <= NOTEBOOK_TITLE_MAX_CHARS:
        raise invalid("title")
    return title


def clean_emoji(value: object) -> str | None:
    """Return the emoji (at most 16 characters); None or blank clears it."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise invalid("emoji")
    emoji = value.strip()
    if len(emoji) > EMOJI_MAX_CHARS:
        raise invalid("emoji")
    return emoji or None


def clean_pinned(value: object) -> bool:
    """Return the flag; anything but a real boolean is refused."""
    if not isinstance(value, bool):
        raise invalid("pinned")
    return value


def _trim_goal(given: dict[str, object]) -> dict[str, object]:
    """Trim a text goal; a blank one becomes `None` (other values: pydantic decides)."""
    goal = given.get("goal")
    if isinstance(goal, str):
        return {**given, "goal": goal.strip() or None}
    return given


def merge_chat_config(current: ChatConfig, value: object) -> ChatConfig:
    """Apply the given chat settings over the current ones and validate the result.

    Keys that are absent keep their value; an unknown key, a bad value, a custom
    prompt over 1000 characters or a goal over 300 raises `InvalidOptionsError`. A
    `custom` style without a prompt is allowed; a blank goal clears the goal.
    """
    if isinstance(value, ChatConfig):
        given = value.model_dump(exclude_unset=True)
    elif isinstance(value, Mapping):
        given = dict(value)
    else:
        raise invalid("chat_config")
    if not set(given) <= set(ChatConfig.model_fields):
        raise invalid("chat_config")
    try:
        return ChatConfig.model_validate({**current.model_dump(), **_trim_goal(given)})
    except ValidationError as exc:
        raise invalid("chat_config") from exc
