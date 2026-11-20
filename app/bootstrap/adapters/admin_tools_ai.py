"""Read-only tools of the AI harness (MCP admin server): requests, prompts, spend."""

from typing import Any

from app.bootstrap.adapters.admin_tools_args import (
    Args,
    invalid,
    limit_arg,
    opt_date,
    opt_uuid,
)
from app.bootstrap.container import Container
from app.interfaces.http.v1.admin_ai.connectors_schemas import PipelineOut
from app.interfaces.http.v1.admin_ai.requests_schemas import (
    PromptDiffOut,
    PromptVersionSummaryOut,
    RequestOut,
)
from app.modules.ai.domain.requests import estimate_tokens
from app.modules.ai.wiring import ConnectorServices, PromptServices
from app.shared.actor import Actor

MAX_DIFF_CHARS = 20_000
LOCALES = frozenset({"", "uz", "ru", "en"})
REQUEST_GROUPS = frozenset({"request", "day", "user", "pipeline"})
SPEND_GROUPS = frozenset({"day", "request", "user"})


def _prompts(c: Container) -> PromptServices:
    if c.ai.prompts is None:  # every composition root builds them
        raise RuntimeError("prompt services are not wired")
    return c.ai.prompts


def _text(args: Args, name: str, maximum: int = 64) -> str:
    value = args.get(name)
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise invalid(f"{name} must be a non-empty string")
    return value


def _opt_text(args: Args, name: str, maximum: int = 96) -> str | None:
    value = args.get(name)
    if value in (None, ""):
        return None
    if not isinstance(value, str) or len(value) > maximum:
        raise invalid(f"{name} must be a short string")
    return value


def _locale(args: Args) -> str:
    value = args.get("locale") or ""
    if value not in LOCALES:
        raise invalid("locale must be uz, ru, en or empty")
    return str(value)


def _opt_int(args: Args, name: str) -> int | None:
    value = args.get(name)
    if value in (None, ""):
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise invalid(f"{name} must be a non-negative integer")
    return value


def _choice(args: Args, name: str, allowed: frozenset[str], default: str) -> str:
    value = args.get(name) or default
    if value not in allowed:
        raise invalid(f"{name} must be one of {sorted(allowed)}")
    return str(value)


async def ai_list_requests(c: Container, args: Args, actor: Actor) -> dict[str, Any]:
    """The registered AI requests with the state of their prompt templates."""
    rows = await _prompts(c).request_admin.list(
        actor,
        owner_app=_opt_text(args, "owner_app", 32),
        pipeline=_opt_text(args, "pipeline", 32),
        include_retired=False,
    )
    return {"items": [RequestOut.of(r).model_dump(mode="json") for r in rows]}


async def ai_list_prompts(c: Container, args: Args, actor: Actor) -> dict[str, Any]:
    """Prompt slots with the active versions, their sizes and the built-in size."""
    task = _opt_text(args, "task", 64)
    rows = await _prompts(c).admin.catalogue(actor)
    return {
        "items": [
            {
                "task": row.slot.task,
                "name": row.slot.name,
                "summary": row.slot.summary,
                "builtin_chars": len(row.slot.builtin),
                "builtin_tokens_est": estimate_tokens(row.slot.builtin),
                "active": [
                    {
                        "locale": v.locale,
                        "version": v.version,
                        "source": v.source,
                        "chars": v.chars,
                        "tokens_est": v.tokens_est,
                    }
                    for v in row.active
                ],
            }
            for row in rows
            if task is None or row.slot.task == task
        ]
    }


async def ai_prompt_versions(c: Container, args: Args, actor: Actor) -> dict[str, Any]:
    """The stored versions of a prompt slot, without their text."""
    rows = await _prompts(c).admin.versions(
        actor, _text(args, "task"), _text(args, "name"), _locale(args)
    )
    return {
        "items": [
            PromptVersionSummaryOut.of(row).model_dump(mode="json") for row in rows
        ]
    }


async def ai_prompt_diff(c: Container, args: Args, actor: Actor) -> dict[str, Any]:
    """The unified diff between two prompt versions, cut at 20 000 characters."""
    found = await _prompts(c).admin.diff(
        actor,
        _text(args, "task"),
        _text(args, "name"),
        locale=_locale(args),
        from_version=_opt_int(args, "from_version"),
        to_version=_opt_int(args, "to_version"),
    )
    out = PromptDiffOut.of(found).model_dump(mode="json")
    out["truncated"] = len(out["diff"]) > MAX_DIFF_CHARS
    out["diff"] = out["diff"][:MAX_DIFF_CHARS]
    return out


async def ai_request_stats(c: Container, args: Args, actor: Actor) -> dict[str, Any]:
    """Averages, totals and cost per request, day, user or pipeline."""
    group = _choice(args, "group_by", REQUEST_GROUPS, "request")
    return await c.ai.analytics.request_stats(
        actor,
        start=opt_date(args, "start", "date_from"),
        end=opt_date(args, "end", "date_to"),
        request_id=_opt_text(args, "request_id"),
        pipeline=_opt_text(args, "pipeline", 32),
        user_id=opt_uuid(args, "user_id"),
        group_by=group,  # type: ignore[arg-type]
    )


async def ai_spend(c: Container, args: Args, actor: Actor) -> dict[str, Any]:
    """Spend per day, request or user, most expensive first."""
    by = _choice(args, "by", SPEND_GROUPS, "day")
    return await c.ai.analytics.spend(
        actor,
        start=opt_date(args, "start", "date_from"),
        end=opt_date(args, "end", "date_to"),
        by=by,  # type: ignore[arg-type]
        request_id=_opt_text(args, "request_id"),
        user_id=opt_uuid(args, "user_id"),
        limit=limit_arg(args, 20, 200),
    )


async def ai_pipelines(c: Container, args: Args, actor: Actor) -> dict[str, Any]:
    """Pipelines with their tasks and effective routes (no secrets)."""
    services: ConnectorServices | None = c.ai.connectors
    if services is None:  # every composition root builds them
        raise RuntimeError("connector services are not wired")
    views = await services.pipelines.list(actor)
    return {"items": [PipelineOut.of(v).model_dump(mode="json") for v in views]}
