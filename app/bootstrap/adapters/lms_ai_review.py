"""The model and web search of the LMS AI review block (gateway adapters)."""

from collections.abc import Sequence
from typing import Any

from app.modules.lms.domain.learning.ai_review import SCHEMA_NAME, ReviewAnswer
from app.modules.notebooks.domain.artifacts.strict import to_strict_schema
from app.settings import Settings
from app.shared.actor import Actor
from app.shared.ai_tasks import AiTask
from app.shared.contracts.ai import AiInvalidOutputError, LlmGateway
from app.shared.contracts.web_search import (
    WebSearchApi,
    WebSearchDisabledError,
    WebSearchQuotaError,
    WebSearchUnavailableError,
)
from app.shared.openui.blocks import fenced
from app.shared.openui.finalize import OpenUiFinalizer
from app.shared.openui.validate import validate_block

from pydantic import ValidationError

_OUTPUT_TOKENS = 3000
_WEB_HITS = 5


class GatewayAiReviewModel:
    """`AiReviewModel` on the LLM gateway (task `lms_ai_review`)."""

    def __init__(self, *, llm: LlmGateway, settings: Settings) -> None:
        """Store the gateway; OpenUI repair follows the global OpenUI switch."""
        self.llm = llm
        self.settings = settings
        self.openui = OpenUiFinalizer(
            llm,
            settings.ai_profile(AiTask.OPENUI_REPAIR),
            enabled=settings.ai.openui_enabled,
        )

    async def answer(
        self, *, system: str, messages: Sequence[dict[str, object]]
    ) -> ReviewAnswer:
        """One strict JSON call; an invalid answer raises AiInvalidOutputError."""
        profile = self.settings.ai_profile(AiTask.LMS_AI_REVIEW)
        done: dict[str, Any] = await self.llm.complete_json(
            model=profile.model,
            system=system,
            messages=list(messages),
            schema_name=SCHEMA_NAME,
            schema=to_strict_schema(ReviewAnswer),
            max_tokens=profile.output_tokens(_OUTPUT_TOKENS),
            provider=profile.provider(require_parameters=True),
            timeout_seconds=float(self.settings.notebooks.llm_timeout_seconds),
            tuning=profile.tuning,
        )
        try:
            return ReviewAnswer.model_validate(done["data"])
        except ValidationError as exc:
            raise AiInvalidOutputError(support_details=SCHEMA_NAME) from exc

    async def finalize(self, source: str) -> str | None:
        """Fence the server-built source; repair it only when it is invalid."""
        if not validate_block(source, "chat"):
            return fenced(source)
        repaired = await self.openui.finalize(fenced(source))
        return repaired or None


class GatewayAiReviewWeb:
    """`AiReviewWeb` on the ai module's web search (stored pages first, Exa next)."""

    def __init__(self, web_search: WebSearchApi) -> None:
        """Store the web search."""
        self.web_search = web_search

    async def search(self, actor: Actor, *, query: str, locale: str) -> str:
        """Return up to five hits as text; disabled, quota or outage give ''."""
        try:
            outcome = await self.web_search.search(
                actor, query=query[:300], locale=locale, kind="fast"
            )
        except (
            WebSearchDisabledError,
            WebSearchQuotaError,
            WebSearchUnavailableError,
        ):
            return ""
        return "\n\n".join(
            f"[{n}] {hit.title}\n{hit.url}\n{hit.snippet}"
            for n, hit in enumerate(outcome.hits[:_WEB_HITS], start=1)
        )
