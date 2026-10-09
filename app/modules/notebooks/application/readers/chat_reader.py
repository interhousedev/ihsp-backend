"""Source kind `chat`: an assistant chat up to a message (§ 3.2.1)."""

from collections.abc import Sequence
from typing import Any
from uuid import UUID

from app.modules.notebooks.application.readers.base import (
    ResolvedSource,
    SourceText,
    clean_title,
    expect_input,
)
from app.modules.notebooks.domain.entities import Source
from app.modules.notebooks.domain.enums import SourceFailure, SourceKind
from app.modules.notebooks.domain.errors import SourceForbiddenError, SourceReadError
from app.modules.notebooks.domain.source_input import ChatInput, SourceInput
from app.shared.contracts.ai import AiQueries

USER = "User"
ASSISTANT = "Assistant"
SEPARATOR = "\n\n"


def latest_ref(ref: dict[str, Any]) -> dict[str, Any]:
    """The ref of a re-sync: no `until_seq`, so the next read takes every message."""
    return {**ref, "until_seq": None}


def pairs_text(messages: Sequence[dict[str, Any]]) -> tuple[str, tuple[int, ...]]:
    """Join the messages as ``User: ...`` / ``Assistant: ...`` pairs.

    Returns:
        The text and the offset where each user+assistant pair starts.
    """
    pairs: list[list[str]] = []
    for message in messages:
        text = str(message.get("text", "")).strip()
        if not text:
            continue
        is_user = message.get("role") == "user"
        if is_user or not pairs:
            pairs.append([])
        pairs[-1].append(f"{USER if is_user else ASSISTANT}: {text}")
    starts: list[int] = []
    offset = 0
    for pair in pairs:
        starts.append(offset)
        offset += len(SEPARATOR.join(pair)) + len(SEPARATOR)
    return SEPARATOR.join(SEPARATOR.join(pair) for pair in pairs), tuple(starts)


class ChatReader:
    """Reads a chat of the owner through `AiQueries.chat_transcript`."""

    def __init__(self, ai: AiQueries) -> None:
        """Store the AI queries."""
        self.ai = ai

    async def resolve(self, user_id: UUID, source_input: SourceInput) -> ResolvedSource:
        """The chat must be the user's own (not an Administration chat)."""
        item = expect_input(source_input, ChatInput)
        transcript = await self.ai.chat_transcript(
            user_id, item.chat_id, item.until_seq
        )
        if transcript is None:
            raise SourceForbiddenError()
        until = item.until_seq if item.until_seq is not None else transcript["last_seq"]
        return ResolvedSource(
            kind=SourceKind.CHAT,
            title=clean_title(transcript.get("title"), "Chat"),
            ref={"chat_id": str(item.chat_id), "until_seq": int(until)},
            ref_key=f"chat:{item.chat_id}",
        )

    async def read(self, source: Source) -> SourceText:
        """The transcript up to `until_seq` (to the latest message after a re-sync)."""
        until = source.ref.get("until_seq")
        transcript = await self.ai.chat_transcript(
            source.owner_id, UUID(str(source.ref["chat_id"])), until
        )
        if transcript is None:
            raise SourceReadError(SourceFailure.DELETED.value)
        text, starts = pairs_text(transcript["messages"])
        last_seq = int(transcript["last_seq"])
        return SourceText(
            text=text,
            unit_starts=starts,
            upstream_version=str(last_seq),
            ref_update={"until_seq": last_seq if until is None else until},
        )

    async def current_version(self, source: Source) -> str | None:
        """The seq of the chat's latest message (None when the chat is gone)."""
        transcript = await self.ai.chat_transcript(
            source.owner_id, UUID(str(source.ref["chat_id"])), 0
        )
        return None if transcript is None else str(transcript["last_seq"])
