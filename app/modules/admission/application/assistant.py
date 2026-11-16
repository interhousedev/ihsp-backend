"""The admission assistant: answers about the student's own data, with tools."""

import datetime as dt
import json
from typing import Any, Final
from uuid import UUID

from app.modules.admission.application.access import AccessPolicy
from app.modules.admission.application.actor import AdmissionContext
from app.modules.admission.application.assistant_tools import TOOLS, ToolBox
from app.modules.admission.application.words import delimit
from app.modules.admission.domain.assistant import (
    HISTORY_TURNS,
    MAX_ROUNDS,
    THREADS_MAX,
    TITLE_MAX,
    Message,
    Reply,
    Screen,
    Thread,
    starter_questions,
)
from app.modules.admission.domain.errors import (
    AdmissionForbiddenError,
    AdmissionNotFoundError,
    CharLimitError,
    ConsentRequiredError,
)
from app.modules.admission.ports.ai import PromptSource, QuotaOf
from app.modules.admission.ports.assistant import (
    AssistantData,
    AssistantModel,
    AssistantRepository,
)
from app.modules.admission.ports.consent import AI, PurposeConsents
from app.modules.admission.ports.student_search import StudentDataSearch
from app.shared.ai_tasks import AiTask
from app.shared.brand import with_brand
from app.shared.clock import Clock
from app.shared.ids import new_id
from app.shared.rate_limit import RateLimiter

_DAY: Final = 24 * 3600
_TOKENS: Final = 1500
_FALLBACK: Final = {
    "uz": "Javob topa olmadim. Savolni boshqacha so‘rab ko‘ring.",
    "ru": "Не удалось найти ответ. Попробуйте переформулировать вопрос.",
    "en": "I could not find an answer. Try asking in other words.",
}


def _clean_attr(value: str) -> str:
    return " ".join(value.replace("<", "").replace(">", "").replace('"', "").split())


def screen_block(screen: Screen) -> str:
    """The untrusted screen text wrapped as data; angle brackets are escaped."""
    body = screen.summary.replace("<", "&lt;").replace(">", "&gt;")
    return (
        f'<screen path="{_clean_attr(screen.path)}" '
        f'title="{_clean_attr(screen.title)}">\n{body}\n</screen>'
    )


def _title(message: str) -> str:
    return " ".join(message.split())[:TITLE_MAX]


class AssistantService:
    """Chat turns, thread history and starter questions of the applicant."""

    def __init__(
        self,
        access: AccessPolicy,
        data: AssistantData,
        search: StudentDataSearch,
        model: AssistantModel,
        repo: AssistantRepository,
        consents: PurposeConsents,
        limiter: RateLimiter,
        quota: QuotaOf,
        prompts: PromptSource,
        clock: Clock,
    ) -> None:
        """Keep the collaborators."""
        self._access = access
        self._data = data
        self._search = search
        self._model = model
        self._repo = repo
        self._consents = consents
        self._limiter = limiter
        self._quota = quota
        self._prompts = prompts
        self._clock = clock

    async def _guard(self, ctx: AdmissionContext, *, ai: bool) -> None:
        if not ctx.admission.is_applicant:
            raise AdmissionForbiddenError(params={"permission": "assistant:use"})
        res = await self._access.resolve(ctx, ctx.user_id)
        if not res.owner:
            raise AdmissionForbiddenError(params={"permission": "assistant:use"})
        if ai:
            granted = (await self._consents.granted([ctx.user_id])).get(
                ctx.user_id, frozenset()
            )
            if AI not in granted:
                raise ConsentRequiredError(params={"purpose": AI})

    async def _own(self, ctx: AdmissionContext, thread_id: UUID) -> Thread:
        thread = await self._repo.get_thread(ctx.user_id, thread_id)
        if thread is None:
            raise AdmissionNotFoundError()
        return thread

    def suggestions(self, path: str, locale: str) -> list[str]:
        """Three starter questions of the screen, from the configuration."""
        return starter_questions(path, locale)

    async def threads(self, ctx: AdmissionContext) -> list[Thread]:
        """The caller's threads, latest first."""
        await self._guard(ctx, ai=False)
        return await self._repo.list_threads(ctx.user_id, THREADS_MAX)

    async def thread(
        self, ctx: AdmissionContext, thread_id: UUID
    ) -> tuple[Thread, list[Message]]:
        """One thread with its messages."""
        await self._guard(ctx, ai=False)
        thread = await self._own(ctx, thread_id)
        return thread, await self._repo.messages(ctx.user_id, thread_id)

    async def delete(self, ctx: AdmissionContext, thread_id: UUID) -> None:
        """Delete one of the caller's threads."""
        await self._guard(ctx, ai=False)
        if not await self._repo.delete_thread(ctx.user_id, thread_id):
            raise AdmissionNotFoundError()

    async def send(
        self,
        ctx: AdmissionContext,
        thread_id: UUID | None,
        message: str,
        screen: Screen | None,
        locale: str,
    ) -> Reply:
        """Answer a message; stores both sides in the thread."""
        message = message.strip()
        if not message:
            raise CharLimitError(params={"field": "message", "limit": 1, "count": 0})
        await self._guard(ctx, ai=True)
        thread = await self._own(ctx, thread_id) if thread_id else None
        history = await self._repo.messages(ctx.user_id, thread.id) if thread else []
        limit = await self._quota(ctx.user_id)
        if limit is not None:
            await self._limiter.hit(
                f"admission:assistant:{ctx.user_id}", limit=limit, window_seconds=_DAY
            )
        system = with_brand(
            await self._prompts.text(AiTask.ADMIT_ASSISTANT, "system", locale)
        )
        box = ToolBox(ctx.user_id, self._data, self._search, screen)
        question = delimit([message])
        if screen is not None:
            question = f"{screen_block(screen)}\n{question}"
        messages = [
            {
                "role": m.role,
                "content": delimit([m.text]) if m.role == "user" else m.text,
            }
            for m in history[-HISTORY_TURNS:]
        ] + [{"role": "user", "content": question}]
        text = await self._loop(system, messages, box)
        text = text.strip() or _FALLBACK.get(locale, _FALLBACK["en"])
        now = self._clock.now()
        if thread is None:
            thread = Thread(new_id(), ctx.user_id, _title(message), now, now)
            await self._repo.create_thread(thread)
        asked = Message(new_id(), thread.id, "user", message, now)
        answer = Message(
            new_id(),
            thread.id,
            "assistant",
            text,
            now + dt.timedelta(microseconds=1),
            box.citations,
            box.actions,
        )
        await self._repo.append(ctx.user_id, [asked, answer])
        return Reply(thread.id, answer.id, text, box.citations, box.actions)

    async def _loop(
        self, system: str, messages: list[dict[str, Any]], box: ToolBox
    ) -> str:
        text = ""
        for round_ in range(MAX_ROUNDS):
            last = round_ == MAX_ROUNDS - 1
            turn = await self._model.turn(
                task=AiTask.ADMIT_ASSISTANT,
                system=system,
                messages=messages,
                tools=[] if last else TOOLS,
                max_tokens=_TOKENS,
            )
            text = str(turn.get("text") or "")
            calls = turn.get("tool_calls") or []
            if not calls or last:
                return "" if calls else text
            messages.append(
                {
                    "role": "assistant",
                    "content": text or None,
                    "tool_calls": [
                        {
                            "id": c["id"],
                            "type": "function",
                            "function": {
                                "name": c["name"],
                                "arguments": json.dumps(c["arguments"]),
                            },
                        }
                        for c in calls
                    ],
                }
            )
            for c in calls:
                args = c["arguments"] if isinstance(c["arguments"], dict) else {}
                result = await box.run(str(c["name"]), args)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": c["id"],
                        "content": json.dumps(result, ensure_ascii=False),
                    }
                )
        return text
