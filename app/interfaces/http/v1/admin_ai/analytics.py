"""AI usage analytics under /v1/admin/ai/analytics (admin only, read-only)."""

from datetime import date
from typing import Annotated, Any, Literal
from uuid import UUID

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_container, require_roles
from app.interfaces.http.v1.admin_ai.analytics_schemas import (
    PromptSizeOut,
    PromptSizesResponse,
    RequestStatsResponse,
    SpendDailyResponse,
    SpendResponse,
)
from app.modules.ai.domain.requests import estimate_tokens
from app.shared.actor import Actor, Role

from fastapi import APIRouter, Depends, Query

router = APIRouter()

ContainerDep = Annotated[Container, Depends(get_container)]
AdminActor = Annotated[Actor, Depends(require_roles(Role.ADMIN))]
StartDay = Annotated[date | None, Query(alias="start")]
EndDay = Annotated[date | None, Query(alias="end")]
RequestFilter = Annotated[str | None, Query(alias="request_id", max_length=96)]
UserFilter = Annotated[UUID | None, Query(alias="user_id")]


@router.get("/analytics/requests", response_model=RequestStatsResponse)
async def request_stats(
    container: ContainerDep,
    actor: AdminActor,
    start: StartDay = None,
    end: EndDay = None,
    request_id: RequestFilter = None,
    pipeline: Annotated[str | None, Query(max_length=32)] = None,
    user_id: UserFilter = None,
    group_by: Literal["request", "day", "user", "pipeline"] = "request",
) -> Any:
    """Averages, totals and cost per request, day, user or pipeline."""
    return await container.ai.analytics.request_stats(
        actor,
        start=start,
        end=end,
        request_id=request_id,
        pipeline=pipeline,
        user_id=user_id,
        group_by=group_by,
    )


@router.get("/analytics/spend", response_model=SpendResponse)
async def spend(
    container: ContainerDep,
    actor: AdminActor,
    start: StartDay = None,
    end: EndDay = None,
    by: Literal["day", "request", "user"] = "day",
    request_id: RequestFilter = None,
    user_id: UserFilter = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> Any:
    """Spend per day, request or user, most expensive first."""
    return await container.ai.analytics.spend(
        actor,
        start=start,
        end=end,
        by=by,
        request_id=request_id,
        user_id=user_id,
        limit=limit,
    )


@router.get("/analytics/spend/daily", response_model=SpendDailyResponse)
async def spend_daily(
    container: ContainerDep,
    actor: AdminActor,
    start: StartDay = None,
    end: EndDay = None,
    request_id: RequestFilter = None,
    user_id: UserFilter = None,
) -> Any:
    """Spend per day and request: the twenty costliest requests, the rest folded."""
    return await container.ai.analytics.spend_daily(
        actor, start=start, end=end, request_id=request_id, user_id=user_id
    )


@router.get("/analytics/prompt-sizes", response_model=PromptSizesResponse)
async def prompt_sizes(
    container: ContainerDep,
    actor: AdminActor,
    task: Annotated[str | None, Query(max_length=64)] = None,
    name: Annotated[str | None, Query(max_length=64)] = None,
) -> PromptSizesResponse:
    """Characters and estimated tokens of every prompt version, the built-in as v0."""
    prompts = container.ai.prompts
    if prompts is None:  # every composition root builds them
        raise RuntimeError("prompt services are not wired")
    now = container.clock.now()
    items: list[PromptSizeOut] = []
    for slot in prompts.registry.slots(task):
        if name is not None and slot.name != name:
            continue
        items.append(
            PromptSizeOut(
                task=slot.task,
                name=slot.name,
                locale="",
                version=0,
                source="code",
                chars=len(slot.builtin),
                tokens_est=estimate_tokens(slot.builtin),
                created_at=now,
                active=False,
            )
        )
        for version in await prompts.admin.versions(actor, slot.task, slot.name):
            items.append(
                PromptSizeOut(
                    task=slot.task,
                    name=slot.name,
                    locale=version.locale,
                    version=version.version,
                    source="code" if version.source == "code" else "admin",
                    chars=version.chars,
                    tokens_est=version.tokens_est,
                    created_at=version.created_at,
                    active=version.active,
                )
            )
    return PromptSizesResponse(items=items)
