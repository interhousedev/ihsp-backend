"""AI request registry and prompt versions under /v1/admin/ai (admin only)."""

from typing import Annotated, Literal

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_container, require_roles
from app.interfaces.http.v1.admin_ai.requests_schemas import (
    PromptDiffOut,
    PromptVersionsResponse,
    PromptVersionSummaryOut,
    RequestOut,
    RequestsResponse,
)
from app.modules.ai.wiring import PromptServices
from app.shared.actor import Actor, Role

from fastapi import APIRouter, Depends, Query

router = APIRouter()

ContainerDep = Annotated[Container, Depends(get_container)]
AdminActor = Annotated[Actor, Depends(require_roles(Role.ADMIN))]
# "" is the text for every locale
VersionLocale = Annotated[Literal["", "uz", "ru", "en"], Query()]


def _prompts(container: Container) -> PromptServices:
    services = container.ai.prompts
    if services is None:  # every composition root builds them
        raise RuntimeError("prompt services are not wired")
    return services


@router.get("/requests", response_model=RequestsResponse)
async def list_requests(
    container: ContainerDep,
    actor: AdminActor,
    owner_app: Annotated[str | None, Query(max_length=32)] = None,
    pipeline: Annotated[str | None, Query(max_length=32)] = None,
    include_retired: bool = False,
) -> RequestsResponse:
    """The registered AI requests, with the state of their prompt templates."""
    rows = await _prompts(container).request_admin.list(
        actor,
        owner_app=owner_app,
        pipeline=pipeline,
        include_retired=include_retired,
    )
    return RequestsResponse(items=[RequestOut.of(row) for row in rows])


@router.get("/requests/{request_id}", response_model=RequestOut)
async def get_request(
    request_id: str, container: ContainerDep, actor: AdminActor
) -> RequestOut:
    """One registered AI request."""
    return RequestOut.of(await _prompts(container).request_admin.get(actor, request_id))


@router.get("/prompts/{task}/{name}/versions", response_model=PromptVersionsResponse)
async def list_prompt_versions(
    task: str,
    name: str,
    container: ContainerDep,
    actor: AdminActor,
    locale: VersionLocale = "",
) -> PromptVersionsResponse:
    """The stored versions of a slot for a locale, without their text."""
    rows = await _prompts(container).admin.versions(actor, task, name, locale)
    return PromptVersionsResponse(
        items=[PromptVersionSummaryOut.of(row) for row in rows]
    )


@router.get("/prompts/{task}/{name}/diff", response_model=PromptDiffOut)
async def get_prompt_diff(
    task: str,
    name: str,
    container: ContainerDep,
    actor: AdminActor,
    locale: VersionLocale = "",
    from_version: Annotated[int | None, Query(alias="from", ge=0)] = None,
    to_version: Annotated[int | None, Query(alias="to", ge=0)] = None,
) -> PromptDiffOut:
    """The unified diff between two versions (0 is the built-in); latest by default."""
    found = await _prompts(container).admin.diff(
        actor,
        task,
        name,
        locale=locale,
        from_version=from_version,
        to_version=to_version,
    )
    return PromptDiffOut.of(found)
