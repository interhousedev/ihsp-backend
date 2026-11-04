"""The real gateway of an eval run: a hard cap on model calls and a JSON report."""

import json
import os
from collections.abc import AsyncIterator
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from app.modules.ai.infrastructure.openrouter import OpenRouterGateway
from app.settings import Settings

import httpx

DEFAULT_MAX_CALLS = 200


class EvalCapReached(RuntimeError):
    """The run has spent its model calls."""


@dataclass(slots=True)
class Spent:
    """What one scenario spent."""

    calls: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    tokens_cached: int = 0
    raw_texts: list[str] = field(default_factory=list)
    models: list[str] = field(default_factory=list)

    def add(self, model: str, text: str, usage: dict[str, Any]) -> None:
        """Count one finished model request."""
        self.calls += 1
        self.tokens_in += int(usage.get("input", 0))
        self.tokens_out += int(usage.get("output", 0))
        self.tokens_cached += int(usage.get("cached", 0))
        self.raw_texts.append(text)
        if model not in self.models:
            self.models.append(model)


class EvalRun:
    """The state of one eval process: the call count, the ledger, the report."""

    def __init__(self, max_calls: int, report_path: str | None) -> None:
        """Start with nothing spent."""
        self.max_calls = max_calls
        self.http_calls = 0
        self.report_path = Path(report_path) if report_path else None
        self.current = Spent()
        self.scenarios: list[dict[str, Any]] = []

    @classmethod
    def from_env(cls) -> "EvalRun":
        """Read the cap and the report path of this run."""
        cap = int(os.environ.get("IHSP_AI_EVAL_MAX_CALLS", DEFAULT_MAX_CALLS))
        return cls(cap, os.environ.get("IHSP_AI_EVAL_REPORT"))

    def begin(self) -> Spent:
        """Start the ledger of the next scenario."""
        self.current = Spent()
        return self.current

    def record(self, scenario: dict[str, Any]) -> None:
        """Add a finished scenario and rewrite the report."""
        self.scenarios.append({**scenario, "spent": _public(self.current)})
        if self.report_path is None:
            return
        spent = [s["spent"] for s in self.scenarios]
        report = {
            "max_calls": self.max_calls,
            "http_calls": self.http_calls,
            "tokens_in": sum(s["tokens_in"] for s in spent),
            "tokens_out": sum(s["tokens_out"] for s in spent),
            "tokens_cached": sum(s["tokens_cached"] for s in spent),
            "scenarios": self.scenarios,
        }
        self.report_path.parent.mkdir(parents=True, exist_ok=True)
        self.report_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8"
        )


def _public(spent: Spent) -> dict[str, Any]:
    return asdict(spent)


class CappedTransport(httpx.AsyncBaseTransport):
    """Counts every HTTP request, retries included, and refuses those over the cap."""

    def __init__(self, run: EvalRun) -> None:
        """Wrap the default transport."""
        self.run = run
        self.inner = httpx.AsyncHTTPTransport()

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        """Send the request unless the run has spent its calls."""
        if self.run.http_calls >= self.run.max_calls:
            raise EvalCapReached(f"over the cap of {self.run.max_calls} model calls")
        self.run.http_calls += 1
        return await self.inner.handle_async_request(request)

    async def aclose(self) -> None:
        """Close the wrapped transport."""
        await self.inner.aclose()


class RecordingGateway:
    """The production gateway, adding each request's text and usage to the ledger."""

    def __init__(self, gateway: OpenRouterGateway, run: EvalRun) -> None:
        """Wrap the gateway."""
        self.gateway = gateway
        self.run = run

    async def complete(self, **kwargs: Any) -> dict[str, Any]:
        """One whole model request."""
        response = await self.gateway.complete(**kwargs)
        self.run.current.add(
            kwargs["model"],
            str(response.get("text") or ""),
            response.get("usage") or {},
        )
        return response

    async def complete_json(self, **kwargs: Any) -> dict[str, Any]:
        """One structured model request."""
        response = await self.gateway.complete_json(**kwargs)
        self.run.current.add(
            kwargs["model"],
            str(response.get("text") or ""),
            response.get("usage") or {},
        )
        return response

    async def stream(self, **kwargs: Any) -> AsyncIterator[dict[str, Any]]:
        """One streamed model request, passed on unchanged."""
        pieces: list[str] = []
        usage: dict[str, Any] = {}
        async for item in self.gateway.stream(**kwargs):
            pieces.append(str(item.get("delta") or ""))
            usage = item.get("usage") or usage
            yield item
        self.run.current.add(kwargs["model"], "".join(pieces), usage)


def real_gateway(settings: Settings, run: EvalRun) -> OpenRouterGateway:
    """The production gateway over the capped transport; the key comes from settings."""
    router = settings.openrouter
    assert router.api_key is not None
    client = httpx.AsyncClient(
        base_url=router.base_url.rstrip("/"),
        timeout=httpx.Timeout(float(router.timeout_seconds), connect=10.0),
        transport=CappedTransport(run),
    )
    return OpenRouterGateway(
        api_key=router.api_key.get_secret_value(),
        base_url=router.base_url,
        app_url=router.app_url,
        app_title=router.app_title,
        timeout_seconds=float(router.timeout_seconds),
        client=client,
        cache_models=settings.ai.prompt_cache_models,
    )
