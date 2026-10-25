"""The Studio output a chat answer may propose (P2, ``action`` of ``NotebookTurn``).

When the student explicitly asks for a study material, the model adds an
``<action>{"kind": ..., "options": {...}, "prompt": "..."}</action>`` tag before the
follow-ups. The tag never reaches the student as text; a valid proposal is returned
next to the messages and the web app shows a card (creation still goes through
``POST artifacts``).
"""

import json
import re
from collections.abc import Sequence
from typing import Any

from app.modules.notebooks.domain.artifacts.registry import handler_for
from app.modules.notebooks.domain.enums import ArtifactKind
from app.modules.notebooks.domain.errors import InvalidOptionsError
from app.modules.notebooks.domain.limits import STUDIO_PROMPT_MAX_CHARS

# `<action>` up to `</action>`, the next `<followups` or the end (an unclosed tag).
_BLOCK = re.compile(
    r"<action(?![A-Za-z0-9_])(?P<rest>.*?)(?:</action\s*>|(?=<followups)|\Z)",
    re.IGNORECASE | re.DOTALL,
)
_JSON_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


def _payload(rest: str) -> str | None:
    """Return the text between ``<action>`` and ``</action>``; None if malformed."""
    head = rest.lstrip()
    if not head.startswith(">"):
        return None
    return _JSON_FENCE.sub("", head[1:].strip())


def _prompt_of(value: object) -> str | None:
    """The focus text: one line, at most 1000 characters, ``None`` when empty."""
    if not isinstance(value, str):
        return None
    flat = " ".join(value.split())[:STUDIO_PROMPT_MAX_CHARS]
    return flat or None


def _kind_of(value: object) -> ArtifactKind | None:
    """Read the ``kind``; unknown names give ``None``."""
    if not isinstance(value, str):
        return None
    try:
        return ArtifactKind(value.strip().lower())
    except ValueError:
        return None


def _checked(data: object) -> dict[str, Any] | None:
    """Validate a parsed proposal with the handler of its kind."""
    if not isinstance(data, dict):
        return None
    kind = _kind_of(data.get("kind"))
    options = {} if data.get("options") is None else data["options"]
    if kind is None or kind.is_course_kind or not isinstance(options, dict):
        return None  # course outputs are never proposed by the notebook chat
    # The model knows no source ids; the student's selection decides at creation.
    options = {key: value for key, value in options.items() if key != "source_ids"}
    prompt = _prompt_of(data.get("prompt"))
    try:
        handler = handler_for(kind)
        parsed = handler.parse_options(options)
        handler.task_block(parsed, prompt)  # a custom report needs a prompt
    except InvalidOptionsError:
        return None
    return {
        "kind": kind.value,
        "options": handler.stored_options(parsed),
        "prompt": prompt,
    }


def _parse(rest: str) -> dict[str, Any] | None:
    """Turn the inside of one ``<action>`` tag into a validated proposal."""
    payload = _payload(rest)
    if not payload:
        return None
    try:
        data = json.loads(payload)
    except (ValueError, RecursionError):
        return None
    return _checked(data)


def _without(raw: str, spans: Sequence[tuple[int, int]]) -> str:
    """Cut the spans out of the text; the pieces around them are joined by a line."""
    pieces: list[str] = []
    position = 0
    for start, end in spans:
        pieces.append(raw[position:start])
        position = end
    pieces.append(raw[position:])
    pieces[0] = pieces[0].rstrip()
    pieces[-1] = pieces[-1].lstrip()
    pieces[1:-1] = [piece.strip() for piece in pieces[1:-1]]
    return "\n".join(piece for piece in pieces if piece)


def split_action(raw: str) -> tuple[str, dict[str, Any] | None]:
    """Cut every ``<action>`` tag off an answer and read the first one.

    The tag is removed in every case (also when unterminated or malformed). The
    proposal is accepted only when the JSON parses, the kind is a supported Studio
    kind and its options pass the validation of that kind (a custom report also needs
    a prompt); anything else gives ``None``.

    Args:
        raw: The raw model answer.

    Returns:
        The answer without the tags and the proposal as ``{"kind", "options",
        "prompt"}`` (the shape of ``ArtifactCreate``; options with defaults filled,
        no ``source_ids``), or ``None``.
    """
    blocks = list(_BLOCK.finditer(raw))
    if not blocks:
        return raw, None
    action = _parse(blocks[0].group("rest"))
    text = _without(raw, [(block.start(), block.end()) for block in blocks])
    return text, action
