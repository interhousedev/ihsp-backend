"""Running a registered AI request: validated arguments, the active template, context.

`AiRequests.scope` checks the arguments against the request's schema, renders the
template (the active version of its prompt slot, else the built-in), and holds the
request context for the usage ledger while the model call runs. The call site keeps
its own gateway call; it asks for the rendered text and the allowed tools.
"""

from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, TypeVar

from app.modules.ai.application.prompt_registry import PromptRegistry
from app.modules.ai.application.request_context import RequestCtx, current_request
from app.modules.ai.domain.args_schema import validate_args
from app.modules.ai.domain.requests import (
    AiRequestArgsInvalidError,
    AiRequestNotFoundError,
    AiRequestSpec,
)

T = TypeVar("T")

_FORMAT_ERRORS = (KeyError, IndexError, ValueError, AttributeError, TypeError)


@dataclass(frozen=True, slots=True)
class RenderedRequest:
    """A request ready to run: its spec, the template text and the version used."""

    spec: AiRequestSpec
    text: str
    version: int
    locale: str

    def allowed_tools(self, tools: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
        """The offered tools the request may use (by name)."""
        allowed = set(self.spec.tools)
        return [tool for tool in tools if tool.get("name") in allowed]


class AiRequests:
    """The registered requests of the process, and how to run one."""

    def __init__(
        self, specs: Sequence[AiRequestSpec], registry: PromptRegistry
    ) -> None:
        """Index the specs by id; the registry resolves their templates."""
        self._specs = {spec.id: spec for spec in specs}
        self._registry = registry

    def specs(self) -> list[AiRequestSpec]:
        """Every registered request, by id."""
        return sorted(self._specs.values(), key=lambda s: s.id)

    def has(self, request_id: str) -> bool:
        """Whether a request with the id is registered."""
        return request_id in self._specs

    def spec(self, request_id: str) -> AiRequestSpec:
        """The request with the id; raises when none is registered."""
        found = self._specs.get(request_id)
        if found is None:
            raise AiRequestNotFoundError(support_details=request_id)
        return found

    @asynccontextmanager
    async def scope(
        self, request_id: str, args: Mapping[str, object], *, locale: str
    ) -> AsyncIterator[RenderedRequest]:
        """Validate, render and hold the request context for the `async with` body."""
        spec = self.spec(request_id)
        problems = validate_args(spec.args_schema, args)
        if problems:
            raise AiRequestArgsInvalidError(support_details="; ".join(problems))
        resolved = await self._registry.resolve(
            spec.template.task, spec.template.name, locale
        )
        text = resolved.text
        if spec.template.template:
            try:
                text = text.format(**args)
            except _FORMAT_ERRORS as exc:
                raise AiRequestArgsInvalidError(
                    support_details=f"template: {exc!r}"
                ) from exc
        token = current_request.set(RequestCtx(spec.id, spec.pipeline))
        try:
            yield RenderedRequest(spec, text, resolved.version, locale)
        finally:
            current_request.reset(token)

    async def run(
        self,
        request_id: str,
        args: Mapping[str, object],
        *,
        locale: str,
        call: Callable[[RenderedRequest], Awaitable[T]],
    ) -> T:
        """Validate and render, then await `call(rendered)` inside the context."""
        async with self.scope(request_id, args, locale=locale) as rendered:
            return await call(rendered)
