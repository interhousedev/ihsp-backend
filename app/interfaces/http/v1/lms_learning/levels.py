"""Routes of level schemes: platform admin and course editors."""

from typing import Annotated, Literal
from uuid import UUID

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_actor, get_container
from app.modules.lms.domain.engagement.levels import (
    Curve,
    LevelScheme,
    LevelTier,
    Scope,
)
from app.shared.actor import Actor

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

ActorDep = Annotated[Actor, Depends(get_actor)]
ContainerDep = Annotated[Container, Depends(get_container)]

router = APIRouter(prefix="/v1", tags=["lms"])


class CurveDoc(BaseModel):
    """A quadratic curve (`base`) or a cumulative table (`steps`)."""

    kind: Literal["quadratic", "table"]
    base: int | None = Field(default=None, ge=1, le=1_000_000)
    steps: list[int] | None = Field(default=None, max_length=1000)

    def to_domain(self) -> Curve:
        """Return the domain curve."""
        if self.kind == "quadratic":
            return Curve.quadratic(self.base or 0)
        return Curve.table(self.steps or [])


class TierDoc(BaseModel):
    """A named band of levels."""

    level_from: int = Field(ge=1, le=1000)
    title: dict[str, str]
    icon: str = Field(max_length=32)
    color: str = Field(pattern=r"^#[0-9a-fA-F]{6}$")
    reward_badge_id: UUID | None = None


class SchemeCreate(BaseModel):
    """A new draft scheme."""

    name: dict[str, str]
    scope: Scope
    course_id: UUID | None = None
    curve: CurveDoc


class TiersBody(BaseModel):
    """The new tiers of a scheme."""

    tiers: list[TierDoc] = Field(max_length=100)


class SchemeOut(BaseModel):
    """A level scheme."""

    id: UUID
    scope: Scope
    course_id: UUID | None
    name: dict[str, str]
    curve: CurveDoc
    tiers: list[TierDoc]
    active: bool


class SchemeList(BaseModel):
    """Every scheme."""

    items: list[SchemeOut]


class ProbeOut(BaseModel):
    """The level a probe XP total reaches under the live and the previewed scheme."""

    before: int
    after: int


class PreviewOut(BaseModel):
    """Learners per level under the live scheme and under the previewed one."""

    before: dict[int, int]
    after: dict[int, int]
    probe: ProbeOut | None = None


class MyLevelOut(BaseModel):
    """The signed-in learner's level in one scope."""

    scope: Scope
    course_id: UUID | None
    xp_total: int
    level: int
    xp_into_level: int
    xp_for_next: int
    tier: TierDoc | None


class AttachBody(BaseModel):
    """The course scheme to make live."""

    scheme_id: UUID


def _out(scheme: LevelScheme) -> SchemeOut:
    curve = scheme.curve
    return SchemeOut(
        id=scheme.id,
        scope=scheme.scope,
        course_id=scheme.course_id,
        name=scheme.name,
        curve=CurveDoc(
            kind=curve.kind,
            base=curve.base if curve.kind == "quadratic" else None,
            steps=list(curve.steps) if curve.kind == "table" else None,
        ),
        tiers=[
            TierDoc(
                level_from=t.level_from,
                title=t.title,
                icon=t.icon,
                color=t.color,
                reward_badge_id=t.reward_badge_id,
            )
            for t in scheme.tiers
        ],
        active=scheme.active,
    )


@router.get("/admin/lms/level-schemes", operation_id="lms_list_level_schemes")
async def list_level_schemes(actor: ActorDep, container: ContainerDep) -> SchemeList:
    """List the level schemes (LMS admins)."""
    found = await container.lms.learning.levels.list_schemes.execute(actor)
    return SchemeList(items=[_out(s) for s in found])


@router.post(
    "/admin/lms/level-schemes",
    operation_id="lms_create_level_scheme",
    status_code=201,
)
async def create_level_scheme(
    body: SchemeCreate, actor: ActorDep, container: ContainerDep
) -> SchemeOut:
    """Create a draft scheme: platform (LMS admin) or course (course editor)."""
    scheme = await container.lms.learning.levels.create.execute(
        actor, body.scope, body.course_id, body.name, body.curve.to_domain()
    )
    return _out(scheme)


@router.put(
    "/admin/lms/level-schemes/{scheme_id}/tiers",
    operation_id="lms_put_level_scheme_tiers",
)
async def put_level_scheme_tiers(
    scheme_id: UUID, body: TiersBody, actor: ActorDep, container: ContainerDep
) -> SchemeOut:
    """Replace the tiers of a scheme."""
    tiers = [
        LevelTier(t.level_from, t.title, t.icon, t.color, t.reward_badge_id)
        for t in body.tiers
    ]
    scheme = await container.lms.learning.levels.update_tiers.execute(
        actor, scheme_id, tiers
    )
    return _out(scheme)


@router.get(
    "/admin/lms/level-schemes/{scheme_id}/preview",
    operation_id="lms_preview_level_scheme",
)
async def preview_level_scheme(
    scheme_id: UUID,
    actor: ActorDep,
    container: ContainerDep,
    xp: Annotated[int | None, Query(ge=0, description="Probe XP total")] = None,
) -> PreviewOut:
    """Show the learners per level before and after the scheme goes live."""
    out = await container.lms.learning.levels.preview.execute(actor, scheme_id, xp)
    return PreviewOut(
        before=out.before,
        after=out.after,
        probe=(
            None
            if out.probe is None
            else ProbeOut(before=out.probe[0], after=out.probe[1])
        ),
    )


@router.get("/lms/me/level", operation_id="lms_my_level")
async def my_level(
    actor: ActorDep,
    container: ContainerDep,
    course_id: Annotated[UUID | None, Query()] = None,
) -> MyLevelOut:
    """Return my level on the platform, or in a course with `course_id`."""
    view = await container.lms.learning.levels.me.execute(actor, course_id)
    tier = view.tier
    return MyLevelOut(
        scope=view.scope,
        course_id=view.course_id,
        xp_total=view.xp_total,
        level=view.level,
        xp_into_level=view.xp_into_level,
        xp_for_next=view.xp_for_next,
        tier=(
            None
            if tier is None
            else TierDoc(
                level_from=tier.level_from,
                title=tier.title,
                icon=tier.icon,
                color=tier.color,
                reward_badge_id=tier.reward_badge_id,
            )
        ),
    )


@router.post(
    "/admin/lms/level-schemes/{scheme_id}:activate",
    operation_id="lms_activate_level_scheme",
)
async def activate_level_scheme(
    scheme_id: UUID, actor: ActorDep, container: ContainerDep
) -> SchemeOut:
    """Make the scheme live for its platform or course."""
    scheme = await container.lms.learning.levels.activate.execute(actor, scheme_id)
    return _out(scheme)


@router.put(
    "/lms/courses/{course_id}/level-scheme",
    operation_id="lms_attach_course_level_scheme",
)
async def attach_course_level_scheme(
    course_id: UUID, body: AttachBody, actor: ActorDep, container: ContainerDep
) -> SchemeOut:
    """Make a scheme of this course live for it (course editors)."""
    scheme = await container.lms.learning.levels.attach.execute(
        actor, course_id, body.scheme_id
    )
    return _out(scheme)
