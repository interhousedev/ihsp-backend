"""Deterministic LlmGateway for development and tests (`OPENROUTER__MODE=fake`)."""

import json
from collections import deque
from typing import Any

from app.modules.ai.domain.prompts import SUMMARY_SYSTEM_PROMPT
from app.shared.ids import new_id

CARD_COUNT = 3
KEPT_REQUESTS = 50


class FakeLlmGateway:
    """Answers from simple rules so the whole assistant flow works without a key.

    The last user message containing "flash" asks for a flash card set, "homework"
    for the homework tool; after a tool result the answer summarizes it; anything
    else is echoed. Usage is `characters // 4`.
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
    ) -> dict[str, Any]:
        """Return a canned response (see the class docstring)."""
        self.requests.append(
            {"model": model, "system": system, "messages": messages, "tools": tools}
        )
        text, calls = self._answer(system, messages)
        size = len(system) + len(json.dumps(messages, default=str))
        usage = {"input": size // 4, "output": len(text) // 4, "cached": 0}
        return {"text": text, "tool_calls": calls, "usage": usage}

    def _answer(
        self, system: str, messages: list[dict[str, Any]]
    ) -> tuple[str, list[dict[str, Any]]]:
        if system.startswith(SUMMARY_SYSTEM_PROMPT[:40]):
            return "(fake) summary of the earlier conversation", []
        if messages and messages[-1].get("role") == "tool":
            return f"(fake) Tool result: {str(messages[-1].get('content'))[:300]}", []
        last = _last_user_text(messages)
        lowered = last.lower()
        if "flash" in lowered:
            return "", [_call("create_flashcard_set", _flashcards(last))]
        if "homework" in lowered:
            return "", [_call("get_homework", {})]
        return f"(fake) {last}", []


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
