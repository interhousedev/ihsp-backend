"""Routes /v1/admin/ai: limits, extensions, usage and prompts (admin only)."""

from datetime import date, datetime, time, timedelta
from typing import Annotated, Literal
from uuid import UUID

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_container, require_roles
from app.interfaces.http.v1.admin_ai.schemas import (
    AiAccessBody,
    AiAccessOut,
    ExtensionBody,
    ExtensionOut,
    ExtensionsResponse,
    GroupBy,
    LimitsBody,
    LimitsResponse,
    PromptAnalyticsResponse,
    PromptBody,
    PromptDetailOut,
    PromptSlotOut,
    PromptSlotsResponse,
    PromptStatsOut,
    PromptVersionOut,
    StudentOut,
    StudentsResponse,
    UsageResponse,
)
from app.modules.ai.wiring import PromptServices
from app.shared.actor import Actor, Role
from app.shared.ai_access import AiAccess
from app.shared.clock import TASHKENT, local_today

from fastapi import APIRouter, Depends, Path, Query, Response, status

router = APIRouter(prefix="/v1/admin/ai", tags=["admin-ai"])

ContainerDep = Annotated[Container, Depends(get_container)]
AdminActor = Annotated[Actor, Depends(require_roles(Role.ADMIN))]
# "" is the text for every locale
PromptLocale = Annotated[Literal["", "uz", "ru", "en"], Query()]
_ANALYTICS_DAYS = 30


@router.get("/limits", response_model=LimitsResponse)
async def get_limits(container: ContainerDep, actor: AdminActor) -> LimitsResponse:
    """Every editable AI limit with its value and environment default."""
    rows = await container.admin.limit_admin.catalogue(actor)
    return LimitsResponse.of(rows)


@router.put("/limits", response_model=LimitsResponse)
async def put_limits(
    body: LimitsBody, container: ContainerDep, actor: AdminActor
) -> LimitsResponse:
    """Change some limits; null resets a limit to its environment value."""
    rows = await container.admin.limit_admin.update(actor, body.limits)
    return LimitsResponse.of(rows)


@router.get("/usage", response_model=UsageResponse, response_model_by_alias=True)
async def get_usage(
    container: ContainerDep,
    actor: AdminActor,
    from_day: Annotated[date | None, Query(alias="from")] = None,
    to_day: Annotated[date | None, Query(alias="to")] = None,
    group_by: GroupBy = "day",
) -> UsageResponse:
    """Tokens, calls and cost of a date range, grouped (Tashkent dates)."""
    view = await container.ai.usage_report.execute(
        actor, from_day=from_day, to_day=to_day, group_by=group_by
    )
    return UsageResponse.of(view)


@router.get("/limit-extensions", response_model=ExtensionsResponse)
async def list_extensions(
    container: ContainerDep,
    actor: AdminActor,
    user_id: Annotated[UUID | None, Query()] = None,
) -> ExtensionsResponse:
    """Every extension, or only the one of a student."""
    rows = await container.admin.limit_admin.extensions(actor, user_id=user_id)
    return ExtensionsResponse(items=[ExtensionOut.of(row) for row in rows])


@router.get("/limit-extensions/students", response_model=StudentsResponse)
async def search_students(
    container: ContainerDep,
    actor: AdminActor,
    q: Annotated[str, Query(min_length=2, max_length=100)],
) -> StudentsResponse:
    """Students whose name or login matches (up to 20)."""
    users = await container.admin.limit_admin.search_students(actor, q.strip())
    return StudentsResponse(items=[StudentOut.of(user) for user in users])


@router.put("/limit-extensions/{user_id}", response_model=ExtensionOut)
async def put_extension(
    user_id: UUID, body: ExtensionBody, container: ContainerDep, actor: AdminActor
) -> ExtensionOut:
    """Create or replace a student's extension (multiplier or values, to a date)."""
    row = await container.admin.limit_admin.save_extension(actor, user_id, body.terms())
    return ExtensionOut.of(row)


@router.get("/users/{user_id}/access", response_model=AiAccessOut)
async def get_ai_access(
    user_id: UUID, container: ContainerDep, actor: AdminActor
) -> AiAccessOut:
    """The AI scopes revoked from a user (chat and notebooks)."""
    access = await container.admin.limit_admin.ai_access(actor, user_id)
    return AiAccessOut.of(user_id, access)


@router.put("/users/{user_id}/access", response_model=AiAccessOut)
async def put_ai_access(
    user_id: UUID, body: AiAccessBody, container: ContainerDep, actor: AdminActor
) -> AiAccessOut:
    """Revoke or restore the chat and notebook AI of a user (audited)."""
    access = AiAccess(
        chat_blocked=body.ai_chat_blocked, notebooks_blocked=body.ai_notebooks_blocked
    )
    saved = await container.admin.limit_admin.set_ai_access(actor, user_id, access)
    return AiAccessOut.of(user_id, saved)


@router.delete(
    "/limit-extensions/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def delete_extension(
    user_id: UUID, container: ContainerDep, actor: AdminActor
) -> Response:
    """Remove the extension of a student."""
    await container.admin.limit_admin.delete_extension(actor, user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _prompts(container: Container) -> PromptServices:
    services = container.ai.prompts
    if services is None:  # every composition root builds them
        raise RuntimeError("prompt services are not wired")
    return services


@router.get("/prompts", response_model=PromptSlotsResponse)
async def list_prompts(
    container: ContainerDep, actor: AdminActor
) -> PromptSlotsResponse:
    """Every editable prompt slot of every AI task, built-in or overridden."""
    rows = await _prompts(container).admin.catalogue(actor)
    return PromptSlotsResponse(items=[PromptSlotOut.of(row) for row in rows])


@router.get(
    "/prompts/analytics",
    response_model=PromptAnalyticsResponse,
    response_model_by_alias=True,
)
async def get_prompt_analytics(
    container: ContainerDep,
    actor: AdminActor,
    task: Annotated[str | None, Query(max_length=64)] = None,
    from_day: Annotated[date | None, Query(alias="from")] = None,
    to_day: Annotated[date | None, Query(alias="to")] = None,
) -> PromptAnalyticsResponse:
    """Calls, latency, tokens, cost, errors and ratings per task and prompt version.

    The range is in Tashkent dates, both ends included; the default is 30 days.
    """
    end_day = to_day or local_today(container.clock)
    start_day = from_day or end_day - timedelta(days=_ANALYTICS_DAYS - 1)
    if start_day > end_day:
        start_day, end_day = end_day, start_day
    start = datetime.combine(start_day, time.min, TASHKENT)
    end = datetime.combine(end_day + timedelta(days=1), time.min, TASHKENT)
    rows = await _prompts(container).analytics.report(actor, task, start, end)
    return PromptAnalyticsResponse(
        from_day=start_day,
        to_day=end_day,
        items=[PromptStatsOut.of(row) for row in rows],
    )


@router.get("/prompts/{task}/{name}", response_model=PromptDetailOut)
async def get_prompt(
    task: str,
    name: str,
    container: ContainerDep,
    actor: AdminActor,
    locale: PromptLocale = "",
) -> PromptDetailOut:
    """The text in force for a locale, the built-in text and every stored version."""
    detail = await _prompts(container).admin.detail(actor, task, name, locale)
    return PromptDetailOut.of(detail, locale)


@router.put("/prompts/{task}/{name}", response_model=PromptVersionOut)
async def put_prompt(
    task: str, name: str, body: PromptBody, container: ContainerDep, actor: AdminActor
) -> PromptVersionOut:
    """Store a new version and make it active; every process uses it within 30 s."""
    version = await _prompts(container).admin.put_version(
        actor, task, name, text=body.text, locale=body.locale, note=body.note
    )
    return PromptVersionOut.of(version)


@router.post(
    "/prompts/{task}/{name}/versions/{version}/activate",
    response_model=PromptVersionOut,
)
async def activate_prompt(
    task: str,
    name: str,
    version: Annotated[int, Path(ge=1)],
    container: ContainerDep,
    actor: AdminActor,
) -> PromptVersionOut:
    """Make a stored version the active one of its locale again (a rollback)."""
    found = await _prompts(container).admin.activate(actor, task, name, version)
    return PromptVersionOut.of(found)


@router.delete(
    "/prompts/{task}/{name}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def revert_prompt(
    task: str,
    name: str,
    container: ContainerDep,
    actor: AdminActor,
    locale: PromptLocale = "",
) -> Response:
    """Go back to the built-in text for a locale; the stored versions stay."""
    await _prompts(container).admin.revert(actor, task, name, locale)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
