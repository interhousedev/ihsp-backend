"""Schemas of educational trajectories."""

import datetime as dt
from collections.abc import Callable
from typing import Any, cast
from uuid import UUID

from app.modules.admission.application.trajectories import (
    TrajectorySummary,
    TrajectoryView,
)
from app.modules.admission.domain.trajectories import (
    DESCRIPTION_MAX,
    MAX_EDGES,
    MAX_NODES,
    MAX_RESOURCES,
    MAX_STAGES,
    RESOURCE_TITLE_MAX,
    SLUG_MAX,
    TITLE_MAX,
    URL_MAX,
    Level,
    NodeKind,
    NodeStatus,
    Resource,
    ResourceHit,
    ResourceKind,
    Trajectory,
)

from pydantic import BaseModel, Field

UrlOf = Callable[[Resource], str]


class I18nTitle(BaseModel):
    """A short text in each language; empty when not written."""

    en: str = Field(default="", max_length=TITLE_MAX)
    ru: str = Field(default="", max_length=TITLE_MAX)
    uz: str = Field(default="", max_length=TITLE_MAX)


class I18nText(BaseModel):
    """A longer text in each language; empty when not written."""

    en: str = Field(default="", max_length=DESCRIPTION_MAX)
    ru: str = Field(default="", max_length=DESCRIPTION_MAX)
    uz: str = Field(default="", max_length=DESCRIPTION_MAX)


def _t(values: dict[str, str]) -> dict[str, str]:
    return {k: values.get(k, "") for k in ("en", "ru", "uz")}


class ResourceIo(BaseModel):
    """A link of a node; `ref` is the LMS course id, library item id or URL."""

    kind: ResourceKind
    ref: str = Field(min_length=1, max_length=URL_MAX)
    title: str = Field(default="", max_length=RESOURCE_TITLE_MAX)


class ResourceOut(ResourceIo):
    """A link with the page it opens."""

    url: str


class NodeIn(BaseModel):
    """One step; `id` is a short key unique in the trajectory."""

    id: str = Field(min_length=1, max_length=40)
    title: I18nTitle
    kind: NodeKind
    level: Level
    description: I18nText = Field(default_factory=I18nText)
    optional: bool = False
    resources: list[ResourceIo] = Field(default_factory=list, max_length=MAX_RESOURCES)


class NodeOut(BaseModel):
    """One step as stored; `position` is its order in the stage."""

    id: str
    title: I18nTitle
    kind: NodeKind
    level: Level
    description: I18nText
    optional: bool
    position: int
    resources: list[ResourceOut]


class StageIn(BaseModel):
    """A column of the roadmap; node order is their position."""

    id: str = Field(min_length=1, max_length=40)
    title: I18nTitle
    nodes: list[NodeIn] = Field(default_factory=list, max_length=MAX_NODES)


class StageOut(BaseModel):
    """A stage with its nodes in order."""

    id: str
    title: I18nTitle
    nodes: list[NodeOut]


class EdgeIo(BaseModel):
    """`before` is a prerequisite of `after` (node ids)."""

    before: str = Field(min_length=1, max_length=40)
    after: str = Field(min_length=1, max_length=40)


class TrajectoryIn(BaseModel):
    """The editable trajectory; the prerequisite graph must be acyclic."""

    slug: str = Field(min_length=1, max_length=SLUG_MAX)
    field: str = Field(description="A study field key (cs_it, medicine_bio, ...).")
    title: I18nTitle
    description: I18nText = Field(default_factory=I18nText)
    published: bool = False
    stages: list[StageIn] = Field(default_factory=list, max_length=MAX_STAGES)
    edges: list[EdgeIo] = Field(default_factory=list, max_length=MAX_EDGES)

    def values(self) -> dict[str, Any]:
        """Plain values for the domain cleaner."""
        return self.model_dump()


class TrajectoryOut(BaseModel):
    """A trajectory with its graph."""

    id: UUID
    slug: str
    field: str
    title: I18nTitle
    description: I18nText
    published: bool
    stages: list[StageOut]
    edges: list[EdgeIo]
    updated_at: dt.datetime | None

    @classmethod
    def of(cls, t: Trajectory, url_of: UrlOf) -> "TrajectoryOut":
        """Map a trajectory; `url_of` turns a resource into its page."""
        return cls(
            id=t.id,
            slug=t.slug,
            field=t.field,
            title=I18nTitle(**_t(t.title)),
            description=I18nText(**_t(t.description)),
            published=t.published,
            stages=[
                StageOut(
                    id=s.id,
                    title=I18nTitle(**_t(s.title)),
                    nodes=[
                        NodeOut(
                            id=n.id,
                            title=I18nTitle(**_t(n.title)),
                            kind=n.kind,
                            level=n.level,
                            description=I18nText(**_t(n.description)),
                            optional=n.optional,
                            position=i,
                            resources=[
                                ResourceOut(
                                    kind=r.kind, ref=r.ref, title=r.title, url=url_of(r)
                                )
                                for r in n.resources
                            ],
                        )
                        for i, n in enumerate(s.nodes)
                    ],
                )
                for s in t.stages
            ],
            edges=[EdgeIo(before=e.before, after=e.after) for e in t.edges],
            updated_at=t.updated_at,
        )


class TrajectorySummaryOut(BaseModel):
    """A trajectory in a list with the caller's progress on required nodes."""

    id: UUID
    slug: str
    field: str
    title: I18nTitle
    description: I18nText
    published: bool
    stage_count: int
    node_count: int
    required_count: int
    done_count: int

    @classmethod
    def of(cls, s: TrajectorySummary) -> "TrajectorySummaryOut":
        """Map a summary."""
        t = s.trajectory
        return cls(
            id=t.id,
            slug=t.slug,
            field=t.field,
            title=I18nTitle(**_t(t.title)),
            description=I18nText(**_t(t.description)),
            published=t.published,
            stage_count=len(t.stages),
            node_count=len(t.nodes()),
            required_count=s.required,
            done_count=s.done,
        )


class TrajectoryListOut(BaseModel):
    """Trajectories ordered by field and slug."""

    items: list[TrajectorySummaryOut]


class NodeProgressOut(BaseModel):
    """The caller's status of one node."""

    node_id: str
    status: NodeStatus


class TrajectoryDetailOut(BaseModel):
    """A trajectory with the caller's progress (empty for staff)."""

    trajectory: TrajectoryOut
    progress: list[NodeProgressOut]
    can_track: bool = Field(description="The caller may mark progress.")

    @classmethod
    def of(
        cls, v: TrajectoryView, url_of: UrlOf, can_track: bool
    ) -> "TrajectoryDetailOut":
        """Map a view."""
        return cls(
            trajectory=TrajectoryOut.of(v.trajectory, url_of),
            progress=[
                NodeProgressOut(node_id=k, status=cast(NodeStatus, s))
                for k, s in sorted(v.progress.items())
            ],
            can_track=can_track,
        )


class NodeProgressIn(BaseModel):
    """A new status of a node; null clears it."""

    status: NodeStatus | None


class ResourceHitOut(BaseModel):
    """A course or book to link."""

    kind: ResourceKind
    ref: str
    title: str
    subtitle: str
    url: str

    @classmethod
    def of(cls, h: ResourceHit) -> "ResourceHitOut":
        """Map a hit."""
        return cls(
            kind=h.kind, ref=h.ref, title=h.title, subtitle=h.subtitle, url=h.url
        )


class ResourceHitListOut(BaseModel):
    """Matching courses or books."""

    items: list[ResourceHitOut]


class TrajectoryStaffListOut(BaseModel):
    """Every trajectory, drafts too."""

    items: list[TrajectorySummaryOut]
