"""Deterministic LlmGateway for development and tests (`OPENROUTER__MODE=fake`)."""

import json
from collections import deque
from collections.abc import AsyncIterator
from typing import Any

from app.modules.ai.domain.prompts import SUMMARY_SYSTEM_PROMPT
from app.modules.ai.infrastructure.fake_author import author_answer, is_author_chat
from app.modules.ai.infrastructure.fake_course import build_course_document
from app.modules.ai.infrastructure.fake_sources import chat_answer, is_notebook_chat
from app.modules.ai.infrastructure.fake_structured import build_document
from app.modules.ai.infrastructure.fake_subjects import (
    SUBJECT_NAMES_SCHEMA,
    subject_names_document,
)
from app.shared.contracts.ai import LlmTuning
from app.shared.ids import new_id

CARD_COUNT = 3
KEPT_REQUESTS = 50
STREAM_CHUNK_CHARS = 12


class FakeLlmGateway:
    """Answers from simple rules so the whole assistant flow works without a key.

    The last user message containing "flash" asks for a flash card set, "homework"
    for the homework tool; after a tool result the answer summarizes it; anything
    else is echoed. Usage is `characters // 4`. The course author assistant has its
    own keyword scenarios (`fake_author`: outline, step, lesson, test, cards, search).

    Notebooks: a request with a `<sources>` block (or the notebook chat system
    prompt) is answered from the first passage with a citation and follow-ups
    (`fake_sources`); `complete_json` builds a valid document for each notebook
    schema name (`fake_structured`) and `stream` yields any answer in small chunks.
    """

    def __init__(self) -> None:
        """Start without recorded requests."""
        self.requests: deque[dict[str, Any]] = deque(maxlen=KEPT_REQUESTS)

    async def complete(
        self,
        *,
        model: str,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        max_tokens: int,
        provider: dict[str, Any] | None = None,
        tuning: LlmTuning | None = None,
    ) -> dict[str, Any]:
        """Return a canned response (see the class docstring)."""
        self._record(
            model, system, messages, tools=tools, provider=provider, tuning=tuning
        )
        text, calls = self._answer(system, messages)
        usage = _usage(system, messages, text)
        return {"text": text, "tool_calls": calls, "usage": usage}

    async def complete_json(
        self,
        *,
        model: str,
        system: str,
        messages: list[dict[str, Any]],
        schema_name: str,
        schema: dict[str, Any],
        max_tokens: int,
        provider: dict[str, Any] | None = None,
        timeout_seconds: float | None = None,
        tuning: LlmTuning | None = None,
    ) -> dict[str, Any]:
        """Return a valid document for the notebook schema `schema_name`."""
        self._record(
            model,
            system,
            messages,
            provider=provider,
            tuning=tuning,
            schema_name=schema_name,
        )
        if schema_name == SUBJECT_NAMES_SCHEMA:
            data: dict[str, Any] = subject_names_document(messages)
        else:
            built = build_course_document(schema_name, messages, system)
            data = built or build_document(schema_name, messages)
        text = json.dumps(data)
        usage = _usage(system, messages, text)
        return {"data": data, "text": text, "usage": {**usage, "cost_micro": None}}

    async def stream(
        self,
        *,
        model: str,
        system: str,
        messages: list[dict[str, Any]],
        max_tokens: int,
        provider: dict[str, Any] | None = None,
        timeout_seconds: float | None = None,
        tuning: LlmTuning | None = None,
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Yield the answer of `complete` in 12-character deltas, then the usage."""
        self._record(
            model,
            system,
            messages,
            tools=tools or [],
            provider=provider,
            tuning=tuning,
            streamed=True,
        )
        text, calls = self._answer(system, messages)
        for start in range(0, len(text), STREAM_CHUNK_CHARS):
            yield {"delta": text[start : start + STREAM_CHUNK_CHARS]}
        last: dict[str, Any] = {
            "usage": {**_usage(system, messages, text), "cost_micro": None}
        }
        if tools and calls:
            last["tool_calls"] = calls
        yield last

    def _record(
        self,
        model: str,
        system: str,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        **extra: Any,
    ) -> None:
        self.requests.append(
            {
                "model": model,
                "system": system,
                "messages": messages,
                "tools": tools or [],
                **extra,
            }
        )

    def _answer(
        self, system: str, messages: list[dict[str, Any]]
    ) -> tuple[str, list[dict[str, Any]]]:
        if system.startswith(SUMMARY_SYSTEM_PROMPT[:40]):
            return "(fake) summary of the earlier conversation", []
        if is_notebook_chat(system, messages):
            return chat_answer(messages), []
        if messages and messages[-1].get("role") == "tool":
            return f"(fake) Tool result: {str(messages[-1].get('content'))[:300]}", []
        last = _last_user_text(messages)
        if is_author_chat(system):
            return author_answer(system, last)
        lowered = last.lower()
        if "flash" in lowered:
            return "", [_call("create_flashcard_set", _flashcards(last))]
        if "homework" in lowered:
            return "", [_call("get_homework", {})]
        return f"(fake) {last}", []


def _usage(system: str, messages: list[dict[str, Any]], text: str) -> dict[str, int]:
    size = len(system) + len(json.dumps(messages, default=str))
    return {"input": size // 4, "output": len(text) // 4, "cached": 0}


def _last_user_text(messages: list[dict[str, Any]]) -> str:
    for message in reversed(messages):
        if message.get("role") == "user":
            return str(message.get("content") or "")
    return ""


def _call(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    return {"id": f"fake_{new_id().hex[-12:]}", "name": name, "arguments": arguments}


def _flashcards(message: str) -> dict[str, Any]:
    topic = " ".join(message.split())[:60] or "topic"
    return {
        "title": f"Flash cards: {topic}"[:100],
        "cards": [
            {"front": f"Question {n}: {topic}", "back": f"Answer {n}"}
            for n in range(1, CARD_COUNT + 1)
        ],
    }
