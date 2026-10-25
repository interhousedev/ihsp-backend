"""Plain-text transcript of messages for the summarizer."""

from collections.abc import Sequence

from app.modules.ai.domain.chat import ChatMessage

MESSAGE_CHARS = 1500
TRANSCRIPT_CHARS = 40_000


def render_transcript(previous: str | None, messages: Sequence[ChatMessage]) -> str:
    """Render the previous summary and the new messages as one data block."""
    lines: list[str] = []
    if previous:
        lines.append(f"Earlier summary: {previous}")
    for message in messages:
        notes = ", ".join(call.tool for call in message.tool_calls)
        suffix = f" [tools: {notes}]" if notes else ""
        text = message.text[:MESSAGE_CHARS]
        lines.append(f"{message.role.value}: {text}{suffix}")
    body = "\n".join(lines)[-TRANSCRIPT_CHARS:]
    return f"<conversation>\n{body}\n</conversation>\nSummarize it."
