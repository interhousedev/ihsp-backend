"""Routes of badge v2: templates, preview, AI draft and platform badges."""

from typing import Annotated, Any
from uuid import UUID

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_actor, get_container
from app.modules.lms.application.badges import BadgeNotFoundError
from app.modules.lms.domain.badge_model import Badge, BadgeScope
from app.modules.lms.domain.badges import BadgeIcon, BadgeShape
from app.shared.actor import Actor, Role

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

ActorDep = Annotated[Actor, Depends(get_actor)]
ContainerDep = Annotated[Container, Depends(get_container)]

router = APIRouter(prefix="/v1", tags=["lms"])


class ParamOut(BaseModel):
    """One tunable parameter of a template."""

    name: str
    min: int | None
    max: int | None
    default: int | str | None


class TemplateOut(BaseModel):
    """A badge template."""

    code: str
    params: list[ParamOut]
    scope: BadgeScope


class TemplateList(BaseModel):
    """The template catalogue."""

    items: list[TemplateOut]


class DesignDoc(BaseModel):
    """The look of a badge."""

    icon: BadgeIcon = BadgeIcon.STAR
    shape: BadgeShape = BadgeShape.CIRCLE
    color: str = "#336699"


class PlatformBadgeBody(BaseModel):
    """A platform badge to create."""

    name: dict[str, str] = Field(default_factory=dict)
    description: dict[str, str] = Field(default_factory=dict)
    design: DesignDoc = Field(default_factory=DesignDoc)
    rule: dict[str, Any] = Field(default_factory=dict)
    # A platform template (e.g. `coach_scholar`) replaces `rule` with its own.
    template_code: str | None = None
    template_params: dict[str, Any] | None = None


class PlatformBadgePatch(BaseModel):
    """Changes of a platform badge."""

    name: dict[str, str] | None = None
    description: dict[str, str] | None = None
    design: DesignDoc | None = None
    rule: dict[str, Any] | None = None
    enabled: bool | None = None


class BadgeOut(BaseModel):
    """A badge with its scope and rule."""

    id: UUID
    scope: BadgeScope
    course_id: UUID | None
    name: dict[str, str]
    description: dict[str, str]
    design: DesignDoc
    rule: dict[str, Any]
    template_code: str | None
    template_params: dict[str, Any] | None
    enabled: bool
    version: int


class BadgeOutList(BaseModel):
    """Platform badges."""

    items: list[BadgeOut]


class PreviewBody(BaseModel):
    """The rule to preview."""

    rule: dict[str, Any]


class PreviewOut(BaseModel):
    """Who would earn the rule."""

    would_earn: int
    sample: list[UUID]
    examined: int
    total: int
    truncated: bool


class DraftBody(BaseModel):
    """The teacher's wish."""

    prompt: str = Field(max_length=500)


class DraftOut(BaseModel):
    """A suggested badge; nothing is stored."""

    template: str
    params: dict[str, Any]
    rule: dict[str, Any]
    name: dict[str, str]
    description: dict[str, str]


def _out(b: Badge) -> BadgeOut:
    return BadgeOut(
        id=b.id,
        scope=b.scope,
        course_id=b.course_id,
        name=b.name,
        description=b.description,
        design=DesignDoc(icon=b.icon, shape=b.shape, color=b.color),
        rule=b.rule,
        template_code=b.template_code,
        template_params=b.template_params,
        enabled=b.enabled,
        version=b.version,
    )


def _design(body: PlatformBadgeBody) -> dict[str, Any]:
    return {
        "name": body.name,
        "description": body.description,
        "icon": body.design.icon,
        "shape": body.design.shape,
        "color": body.design.color,
    }


def _admin(actor: Actor) -> None:
    actor.require(Role.LMS_ADMIN)


@router.get("/lms/badge-templates", operation_id="lms_list_badge_templates")
async def list_badge_templates(
    actor: ActorDep, container: ContainerDep
) -> TemplateList:
    """Return the badge templates (any signed-in user)."""
    items = container.lms.learning.badge_authoring.templates.execute(None)
    return TemplateList(
        items=[
            TemplateOut(
                code=t.code,
                params=[
                    ParamOut(name=p.name, min=p.min, max=p.max, default=p.default)
                    for p in t.params
                ],
                scope=t.scope,
            )
            for t in items
        ]
    )


@router.post(
    "/lms/courses/{course_id}/badges:preview", operation_id="lms_preview_badge"
)
async def preview_badge(
    course_id: UUID, body: PreviewBody, actor: ActorDep, container: ContainerDep
) -> PreviewOut:
    """Count who would earn a rule (course staff with `edit`); awards nothing."""
    out = await container.lms.learning.badge_authoring.preview.execute(
        actor, course_id, body.rule
    )
    return PreviewOut(
        would_earn=out.would_earn,
        sample=out.sample,
        examined=out.examined,
        total=out.total,
        truncated=out.truncated,
    )


@router.post("/admin/lms/badges:preview", operation_id="lms_admin_preview_badge")
async def admin_preview_badge(
    body: PreviewBody, actor: ActorDep, container: ContainerDep
) -> PreviewOut:
    """Count who on the platform would earn a rule (LMS administrators)."""
    out = await container.lms.learning.badge_authoring.preview_platform.execute(
        actor, body.rule
    )
    return PreviewOut(
        would_earn=out.would_earn,
        sample=out.sample,
        examined=out.examined,
        total=out.total,
        truncated=out.truncated,
    )


@router.post("/lms/courses/{course_id}/badges:draft", operation_id="lms_draft_badge")
async def draft_badge(
    course_id: UUID, body: DraftBody, actor: ActorDep, container: ContainerDep
) -> DraftOut:
    """Suggest a rule and names from a wish (course staff with `edit`)."""
    d = await container.lms.learning.badge_authoring.draft.execute(
        actor, course_id, body.prompt
    )
    return DraftOut(
        template=d.template,
        params=d.params,
        rule=d.rule,
        name=d.name,
        description=d.description,
    )


@router.get("/admin/lms/badges", operation_id="lms_admin_list_badges")
async def admin_list_badges(actor: ActorDep, container: ContainerDep) -> BadgeOutList:
    """Return the platform badges (LMS administrators)."""
    _admin(actor)
    rows = await container.lms.learning.badge_authoring.store.list_platform()
    return BadgeOutList(items=[_out(b) for b in rows])


@router.post(
    "/admin/lms/badges", operation_id="lms_admin_create_badge", status_code=201
)
async def admin_create_badge(
    body: PlatformBadgeBody, actor: ActorDep, container: ContainerDep
) -> BadgeOut:
    """Create a platform badge on an aggregate event (LMS administrators)."""
    _admin(actor)
    badge = await container.lms.learning.badge_authoring.create_platform.execute(
        actor, body.rule, _design(body), body.template_code, body.template_params
    )
    return _out(badge)


@router.patch("/admin/lms/badges/{badge_id}", operation_id="lms_admin_update_badge")
async def admin_update_badge(
    badge_id: UUID,
    body: PlatformBadgePatch,
    actor: ActorDep,
    container: ContainerDep,
) -> BadgeOut:
    """Change a platform badge; a new rule backfills (LMS administrators)."""
    _admin(actor)
    design: dict[str, Any] | None = None
    if body.design or body.name or body.description:
        design = {"name": body.name or {}, "description": body.description or {}}
        if body.design:
            design |= {
                "icon": body.design.icon,
                "shape": body.design.shape,
                "color": body.design.color,
            }
    badge = await container.lms.learning.badge_authoring.update.execute(
        actor, badge_id, rule=body.rule, enabled=body.enabled, design=design
    )
    return _out(badge)


@router.delete(
    "/admin/lms/badges/{badge_id}",
    operation_id="lms_admin_delete_badge",
    status_code=204,
)
async def admin_delete_badge(
    badge_id: UUID, actor: ActorDep, container: ContainerDep
) -> None:
    """Delete a platform badge with its awards (LMS administrators)."""
    _admin(actor)
    store = container.lms.learning.badge_authoring.store
    badge = await store.get(badge_id)
    if badge is None or badge.scope is not BadgeScope.PLATFORM:
        raise BadgeNotFoundError()
    await store.delete(badge_id)
