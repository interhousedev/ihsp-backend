"""Reads the ``<sources>`` block of a notebook prompt (for the fake model).

The block is built by the notebooks module: ``[S1:P1] passage text`` at the start of
a line, each passage running to the next label or tag (it may hold blank lines),
wrapped in ``<source ...>`` tags.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

CHAT_SYSTEM_PREFIX = "You are the notebook assistant of the IHT student platform"
NO_ANSWER = "(fake) The sources do not say.\n<followups>[]</followups>"
FOLLOWUPS = '["First follow-up?","Second follow-up?","Third follow-up?"]'
ANSWER_CHARS = 100
PLACEHOLDER = "The sources do not contain any text."

# A passage runs from its label to the next label or tag: it may hold blank lines
# (a heading, a paragraph and a list are one passage of the chunker).
_PASSAGE = re.compile(
    r"^\[(S\d+:P\d+)\] (.*?)"
    r"(?=\n</source|\n<source[ >]|\n\[S\d+:P\d+\] |\n</?sources>|\Z)",
    re.MULTILINE | re.DOTALL,
)
_LABEL = re.compile(r"S\d+:P\d+")
_TAG = re.compile(r"<[^>\n]{1,200}>")


@dataclass(frozen=True, slots=True)
class FakePassage:
    """A passage found in the prompt; ``label`` is empty for unlabelled text."""

    label: str
    text: str

    @property
    def refs(self) -> list[str]:
        """The ``refs`` list of a document item that cites this passage."""
        return [self.label] if self.label else []


def message_text(message: dict[str, Any]) -> str:
    """Return the text of a message whose content is a string or a list of parts."""
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            str(part.get("text", ""))
            for part in content
            if isinstance(part, dict) and part.get("type") == "text"
        )
    return ""


def last_user_text(messages: Sequence[dict[str, Any]]) -> str:
    """Return the text of the last user message ("" when there is none)."""
    for message in reversed(messages):
        if message.get("role") == "user":
            return message_text(message)
    return ""


def find_passages(messages: Sequence[dict[str, Any]]) -> list[FakePassage]:
    """Return the labelled passages of all messages, in order, without repeats."""
    text = "\n\n".join(message_text(m) for m in messages)
    found: dict[str, FakePassage] = {}
    for label, body in _PASSAGE.findall(text):
        found.setdefault(label, FakePassage(label, body.strip()))
    return list(found.values())


def plain_passages(messages: Sequence[dict[str, Any]]) -> list[FakePassage]:
    """Return the paragraphs of the user messages (tags removed, no labels)."""
    paragraphs: list[FakePassage] = []
    for message in messages:
        if message.get("role") != "user":
            continue
        for block in re.split(r"\n[ \t]*\n", _TAG.sub("\n\n", message_text(message))):
            flat = " ".join(block.split())
            if flat:
                paragraphs.append(FakePassage("", flat))
    return paragraphs


def document_passages(messages: Sequence[dict[str, Any]]) -> list[FakePassage]:
    """Return the passages a fake document is built from (never empty)."""
    return (
        find_passages(messages)
        or plain_passages(messages)
        or [FakePassage("", PLACEHOLDER)]
    )


def is_notebook_chat(system: str, messages: Sequence[dict[str, Any]]) -> bool:
    """Return True for the grounded notebook chat (system prompt or ``<sources>``)."""
    return system.startswith(CHAT_SYSTEM_PREFIX) or any(
        m.get("role") == "user" and "<sources>" in message_text(m) for m in messages
    )


def chat_answer(messages: Sequence[dict[str, Any]]) -> str:
    """Return the fake grounded answer with one citation and three follow-ups.

    It cites the passage named in the last user message (an anchored question) when
    that label exists, else ``S1:P1``, else the first passage. Without passages the
    sources "do not say".
    """
    passages = find_passages(messages)
    if not passages:
        return NO_ANSWER
    by_label = {p.label: p for p in passages}
    chosen = by_label.get(_anchored_label(messages, by_label))
    chosen = chosen or by_label.get("S1:P1") or passages[0]
    return (
        f"(fake) {chosen.text[:ANSWER_CHARS]} [[{chosen.label}]]\n"
        f"<followups>{FOLLOWUPS}</followups>"
    )


def _anchored_label(
    messages: Sequence[dict[str, Any]], known: dict[str, FakePassage]
) -> str:
    """Return the first known label named in the last user message, or ''."""
    last = last_user_text(messages)
    if "<sources>" in last:
        return ""
    return next((label for label in _LABEL.findall(last) if label in known), "")
