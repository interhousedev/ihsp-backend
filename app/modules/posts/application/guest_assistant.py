"""The guest assistant: answers parents and applicants from guest knowledge only.

It has one tool, `search_knowledge`, backed by `GuestKnowledge` (entries marked
`accessible_to_guest`). It has no personal tools and never sees any user data.
"""

import json
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import Any, Final, Protocol

from app.modules.posts.domain.errors import GuestBusyError, GuestLimitError
from app.modules.posts.ports.repositories import GuestKnowledge
from app.shared.ai_tasks import AiTask, ModelProfile
from app.shared.base_error import RateLimitedError
from app.shared.contracts.ai import LlmGateway

SEARCH_TOOL: Final = "search_knowledge"
GUEST_TOOLS: Final[tuple[dict[str, Any], ...]] = (
    {
        "type": "function",
        "function": {
            "name": SEARCH_TOOL,
            "description": (
                "Search the public information about International House Tashkent "
                "lyceum (admission, programmes, fees, contacts, events)."
            ),
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
                "additionalProperties": False,
            },
        },
    },
)
MAX_ROUNDS: Final = 3
MAX_QUESTION: Final = 2000
LANGUAGE_NAMES: Final = {"uz": "Uzbek", "ru": "Russian", "en": "English"}

SYSTEM: Final = (
    "You are the public assistant of the Academic Lyceum International House "
    "Tashkent (IHT) in Telegram. You talk to parents and applicants, not to "
    "students. Answer only from the results of search_knowledge; when they do not "
    "answer the question, say so and suggest contacting the lyceum. Never invent "
    "facts, fees or dates. You have no access to any student, mark, schedule or "
    "personal data and must refuse such requests. Keep answers short. Use simple "
    "Markdown (bold, lists, links). Reply in {language}."
)


class HitLimiter(Protocol):
    """`RateLimiter.hit`: raises RateLimitedError over the limit."""

    async def hit(self, key: str, *, limit: int, window_seconds: int) -> int:
        """Count one hit."""
        ...


@dataclass(frozen=True, slots=True)
class GuestLimits:
    """Soft limits per Telegram user."""

    per_minute: int
    per_day: int
    global_per_day: int


class GuestAssistant:
    """Streams an answer for one guest question."""

    def __init__(
        self,
        *,
        llm: LlmGateway,
        knowledge: GuestKnowledge,
        limiter: HitLimiter,
        limits: Callable[[], GuestLimits],
        profile: Callable[[AiTask], ModelProfile],
    ) -> None:
        """Store the collaborators."""
        self.llm = llm
        self.knowledge = knowledge
        self.limiter = limiter
        self.limits = limits
        self.profile = profile

    async def check_limits(self, telegram_user_id: int) -> None:
        """Count the question.

        GuestLimitError over the user's minute or day limit; GuestBusyError when the
        guests of all users together reached the global daily ceiling (the cost cap).
        """
        limits = self.limits()
        try:
            await self.limiter.hit(
                f"guest:min:{telegram_user_id}",
                limit=limits.per_minute,
                window_seconds=60,
            )
            await self.limiter.hit(
                f"guest:day:{telegram_user_id}",
                limit=limits.per_day,
                window_seconds=86400,
            )
        except RateLimitedError as error:
            raise GuestLimitError(params=error.params) from error
        try:
            await self.limiter.hit(
                "guest:global:day", limit=limits.global_per_day, window_seconds=86400
            )
        except RateLimitedError as error:
            raise GuestBusyError(params=error.params) from error

    async def _tool(self, call: dict[str, Any]) -> str:
        if call.get("name") != SEARCH_TOOL:
            return json.dumps({"error": "unknown tool"})
        args = call.get("arguments") or {}
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except ValueError:
                args = {}
        query = str(args.get("query") or "")[:500]
        hits = await self.knowledge.search(query, limit=5) if query else []
        return json.dumps(
            [{"title": h.title, "text": h.value} for h in hits], ensure_ascii=False
        )

    async def answer(
        self, telegram_user_id: int, question: str, *, locale: str
    ) -> AsyncIterator[str]:
        """Check the limits, then yield the answer text piece by piece."""
        await self.check_limits(telegram_user_id)
        async for delta in self.stream_answer(question, locale=locale):
            yield delta

    async def stream_answer(self, question: str, *, locale: str) -> AsyncIterator[str]:
        """Yield the answer piece by piece (the caller has checked the limits)."""
        profile = self.profile(AiTask.GUEST_CHAT)
        system = SYSTEM.format(language=LANGUAGE_NAMES.get(locale, "English"))
        messages: list[dict[str, Any]] = [
            {"role": "user", "content": question.strip()[:MAX_QUESTION]}
        ]
        for round_no in range(MAX_ROUNDS):
            last_round = round_no == MAX_ROUNDS - 1
            text: list[str] = []
            calls: list[dict[str, Any]] = []
            async for item in self.llm.stream(
                model=profile.model,
                system=system,
                messages=messages,
                max_tokens=profile.output_tokens(1024),
                provider=profile.provider(),
                tuning=profile.tuning,
                tools=None if last_round else [dict(t) for t in GUEST_TOOLS],
            ):
                if item.get("delta"):
                    text.append(item["delta"])
                    yield item["delta"]
                calls.extend(item.get("tool_calls") or [])
            if not calls:
                return
            messages.append(
                {
                    "role": "assistant",
                    "content": "".join(text) or None,
                    "tool_calls": [
                        {
                            "id": c["id"],
                            "type": "function",
                            "function": {
                                "name": c["name"],
                                "arguments": json.dumps(
                                    c.get("arguments") or {}, ensure_ascii=False
                                ),
                            },
                        }
                        for c in calls
                    ],
                }
            )
            for call in calls:
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call["id"],
                        "content": await self._tool(call),
                    }
                )
