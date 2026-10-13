"""The language model as notebooks use it: tasks, privacy options, weighted usage."""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

from app.modules.notebooks.domain.tokens import Usage
from app.settings import Settings
from app.shared.ai.prompt_cache import context_message
from app.shared.ai_tasks import AiTask, ModelProfile
from app.shared.contracts.ai import LlmGateway


@dataclass(frozen=True, slots=True)
class JsonCompletion:
    """A structured answer: the parsed object, the raw text and the usage."""

    data: dict[str, Any]
    text: str
    usage: Usage
    model: str


@dataclass(frozen=True, slots=True)
class TextCompletion:
    """A plain answer."""

    text: str
    usage: Usage
    model: str


@dataclass(frozen=True, slots=True)
class StreamItem:
    """Either a piece of text (`delta`) or the final `usage` (the last item)."""

    delta: str | None = None
    usage: Usage | None = None


class NotebookLlm:
    """Wraps `LlmGateway`: the model of each task, `data_collection` and caching.

    Callers name the task (`AiTask.NOTEBOOK_CHAT`, `STUDIO_QUIZ`, ...); the model,
    temperature and routing come from `AI__...` in the settings.
    """

    def __init__(self, gateway: LlmGateway, settings: Settings) -> None:
        """Store the gateway and the settings."""
        self.gateway = gateway
        self.settings = settings

    def profile(self, task: AiTask) -> ModelProfile:
        """The model and parameters of a task."""
        return self.settings.ai_profile(task)

    def model(self, task: AiTask = AiTask.NOTEBOOK_CHAT) -> str:
        """The model id a task runs with."""
        return self.profile(task).model

    def max_tokens(self, task: AiTask, default: int) -> int:
        """The answer size: the task's setting, else the call site's `default`."""
        return self.profile(task).output_tokens(default)

    def context_message(
        self,
        block: str,
        task: AiTask = AiTask.NOTEBOOK_CHAT,
        *,
        extra: str | None = None,
    ) -> dict[str, Any]:
        """The first user message (`<sources>`); caching models get a cache mark.

        `extra` (the summary of older turns) follows the cached block.
        """
        ai = self.settings.ai
        return context_message(
            block,
            model=self.model(task),
            prefixes=ai.prompt_cache_models,
            min_chars=ai.prompt_cache_min_chars,
            extra=extra,
        )

    async def json(
        self,
        *,
        task: AiTask,
        system: str,
        messages: list[dict[str, Any]],
        schema_name: str,
        schema: dict[str, Any],
        max_tokens: int,
    ) -> JsonCompletion:
        """Ask for a JSON document (strict schema); raises the gateway's errors."""
        profile = self.profile(task)
        result = await self.gateway.complete_json(
            model=profile.model,
            system=system,
            messages=messages,
            schema_name=schema_name,
            schema=schema,
            max_tokens=max_tokens,
            provider=profile.provider(require_parameters=True),
            timeout_seconds=float(self.settings.notebooks.llm_timeout_seconds),
            tuning=profile.tuning,
        )
        return JsonCompletion(
            data=result["data"],
            text=result.get("text", ""),
            usage=Usage.from_gateway(result.get("usage", {})),
            model=profile.model,
        )

    async def text(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        max_tokens: int,
        task: AiTask = AiTask.NOTEBOOK_CHAT,
    ) -> TextCompletion:
        """Ask for a plain answer without tools."""
        profile = self.profile(task)
        result = await self.gateway.complete(
            model=profile.model,
            system=system,
            messages=messages,
            tools=[],
            max_tokens=max_tokens,
            provider=profile.provider(),
            tuning=profile.tuning,
        )
        return TextCompletion(
            text=result.get("text", ""),
            usage=Usage.from_gateway(result.get("usage", {})),
            model=profile.model,
        )

    async def stream(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        max_tokens: int,
        task: AiTask = AiTask.NOTEBOOK_CHAT,
    ) -> AsyncIterator[StreamItem]:
        """Stream a plain answer; the last item carries the usage."""
        profile = self.profile(task)
        async for item in self.gateway.stream(
            model=profile.model,
            system=system,
            messages=messages,
            max_tokens=max_tokens,
            provider=profile.provider(),
            timeout_seconds=float(self.settings.notebooks.llm_timeout_seconds),
            tuning=profile.tuning,
        ):
            if "usage" in item:
                yield StreamItem(usage=Usage.from_gateway(item["usage"]))
            else:
                yield StreamItem(delta=str(item.get("delta", "")))
