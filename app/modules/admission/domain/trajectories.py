"""Educational trajectories: staged roadmaps of topics, courses and books.

A trajectory is a directed acyclic graph of nodes laid out in stages. An edge
`(before, after)` says `before` is a prerequisite of `after`.
"""

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Final, Literal, get_args
from urllib.parse import urlsplit
from uuid import UUID

from app.modules.admission.domain.country_facts import OPPORTUNITY_FIELDS
from app.shared.base_error import ValidationFailedError

NodeKind = Literal["topic", "course", "book", "project", "exam", "milestone"]
Level = Literal["beginner", "intermediate", "advanced"]
ResourceKind = Literal["lms_course", "library_book", "url"]
NodeStatus = Literal["done", "in_progress", "skipped"]

NODE_KINDS: Final[tuple[str, ...]] = get_args(NodeKind)
LEVELS: Final[tuple[str, ...]] = get_args(Level)
RESOURCE_KINDS: Final[tuple[str, ...]] = get_args(ResourceKind)
NODE_STATUSES: Final[tuple[str, ...]] = get_args(NodeStatus)
LOCALES: Final = ("en", "ru", "uz")

SLUG_RE: Final = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
KEY_RE: Final = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")
SLUG_MAX: Final = 80
TITLE_MAX: Final = 160
DESCRIPTION_MAX: Final = 2000
RESOURCE_TITLE_MAX: Final = 300
URL_MAX: Final = 1000
MAX_STAGES: Final = 12
MAX_NODES: Final = 150
MAX_RESOURCES: Final = 8
MAX_EDGES: Final = 400

I18n = dict[str, str]


@dataclass(frozen=True, slots=True)
class Resource:
    """A link of a node: an LMS course id, a library item id or a web address."""

    kind: ResourceKind
    ref: str
    title: str


@dataclass(frozen=True, slots=True)
class Node:
    """One step of a trajectory."""

    id: str
    title: I18n
    kind: NodeKind
    level: Level
    description: I18n = field(default_factory=dict)
    optional: bool = False
    resources: tuple[Resource, ...] = ()


@dataclass(frozen=True, slots=True)
class Stage:
    """A column of the roadmap; the order of `nodes` is their position."""

    id: str
    title: I18n
    nodes: tuple[Node, ...] = ()


@dataclass(frozen=True, slots=True)
class Edge:
    """`before` is a prerequisite of `after`."""

    before: str
    after: str


@dataclass(frozen=True, slots=True)
class Trajectory:
    """A roadmap of one study field."""

    id: UUID
    slug: str
    field: str
    title: I18n
    description: I18n
    published: bool
    stages: tuple[Stage, ...] = ()
    edges: tuple[Edge, ...] = ()
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def nodes(self) -> list[Node]:
        """Every node, stage by stage."""
        return [n for s in self.stages for n in s.nodes]

    def matches(self, query: str) -> bool:
        """Whether a title or description in any language holds `query`."""
        q = query.casefold()
        texts = [*self.title.values(), *self.description.values()]
        return any(q in t.casefold() for t in texts)


@dataclass(frozen=True, slots=True)
class ResourceHit:
    """A course or book a curator may link to a node."""

    kind: ResourceKind
    ref: str
    title: str
    subtitle: str
    url: str


def _invalid(name: str, reason: str = "invalid") -> ValidationFailedError:
    return ValidationFailedError(params={"field": name, "reason": reason})


def _text(value: Any, name: str, limit: int, *, required: bool = False) -> str:
    text = str(value or "").strip()
    if len(text) > limit or (required and not text):
        raise _invalid(name)
    return text


def _i18n(raw: Any, name: str, limit: int, *, required: bool) -> I18n:
    raw = raw if isinstance(raw, Mapping) else {}
    out = {loc: _text(raw.get(loc), name, limit) for loc in LOCALES}
    if required and not any(out.values()):
        raise _invalid(name, "required")
    return {k: v for k, v in out.items() if v}


def _key(value: Any, name: str) -> str:
    key = str(value or "")
    if not KEY_RE.match(key):
        raise _invalid(name)
    return key


def _member(value: Any, allowed: tuple[str, ...], name: str) -> Any:
    if value not in allowed:
        raise _invalid(name)
    return value


def _resource(raw: Mapping[str, Any]) -> Resource:
    kind = _member(raw.get("kind"), RESOURCE_KINDS, "resources.kind")
    ref = _text(raw.get("ref"), "resources.ref", URL_MAX, required=True)
    if kind == "url":
        parts = urlsplit(ref)
        if parts.scheme not in ("http", "https") or not parts.netloc:
            raise _invalid("resources.ref", "url")
    elif kind == "library_book":
        try:
            ref = str(UUID(ref))
        except ValueError:
            raise _invalid("resources.ref") from None
    elif not KEY_RE.match(ref) and not _is_uuid(ref):
        raise _invalid("resources.ref")
    title = _text(raw.get("title"), "resources.title", RESOURCE_TITLE_MAX)
    return Resource(kind=kind, ref=ref, title=title or ref)


def _is_uuid(value: str) -> bool:
    try:
        UUID(value)
    except ValueError:
        return False
    return True


def _node(raw: Mapping[str, Any]) -> Node:
    resources = [_resource(r) for r in raw.get("resources") or ()]
    if len(resources) > MAX_RESOURCES:
        raise _invalid("resources", "too_many")
    return Node(
        id=_key(raw.get("id"), "nodes.id"),
        title=_i18n(raw.get("title"), "nodes.title", TITLE_MAX, required=True),
        kind=_member(raw.get("kind"), NODE_KINDS, "nodes.kind"),
        level=_member(raw.get("level"), LEVELS, "nodes.level"),
        description=_i18n(
            raw.get("description"), "nodes.description", DESCRIPTION_MAX, required=False
        ),
        optional=bool(raw.get("optional")),
        resources=tuple(dict.fromkeys(resources)),
    )


def check_acyclic(node_ids: Iterable[str], edges: Iterable[Edge]) -> None:
    """Raise when the prerequisite graph has a cycle (Kahn's algorithm)."""
    incoming: dict[str, int] = dict.fromkeys(node_ids, 0)
    after: dict[str, list[str]] = {n: [] for n in incoming}
    for e in edges:
        after[e.before].append(e.after)
        incoming[e.after] += 1
    ready = [n for n, k in incoming.items() if k == 0]
    seen = 0
    while ready:
        n = ready.pop()
        seen += 1
        for m in after[n]:
            incoming[m] -= 1
            if incoming[m] == 0:
                ready.append(m)
    if seen != len(incoming):
        raise _invalid("edges", "cycle")


def _stages(values: Mapping[str, Any]) -> tuple[Stage, ...]:
    stages_raw = list(values.get("stages") or ())
    if len(stages_raw) > MAX_STAGES:
        raise _invalid("stages", "too_many")
    stages = tuple(
        Stage(
            id=_key(s.get("id"), "stages.id"),
            title=_i18n(s.get("title"), "stages.title", TITLE_MAX, required=True),
            nodes=tuple(_node(n) for n in s.get("nodes") or ()),
        )
        for s in stages_raw
    )
    if len({s.id for s in stages}) != len(stages):
        raise _invalid("stages.id", "duplicate")
    return stages


def _edges(values: Mapping[str, Any], ids: list[str]) -> tuple[Edge, ...]:
    known = set(ids)
    edges: list[Edge] = []
    for raw in values.get("edges") or ():
        edge = Edge(before=str(raw.get("before")), after=str(raw.get("after")))
        if edge.before not in known or edge.after not in known:
            raise _invalid("edges", "unknown_node")
        if edge.before == edge.after:
            raise _invalid("edges", "cycle")
        edges.append(edge)
    unique = tuple(dict.fromkeys(edges))
    if len(unique) > MAX_EDGES:
        raise _invalid("edges", "too_many")
    check_acyclic(ids, unique)
    return unique


def clean_trajectory(values: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and normalize the editable fields of a trajectory."""
    slug = _text(values.get("slug"), "slug", SLUG_MAX, required=True).lower()
    if not SLUG_RE.match(slug):
        raise _invalid("slug")
    stages = _stages(values)
    ids = [n.id for s in stages for n in s.nodes]
    if len(ids) > MAX_NODES:
        raise _invalid("nodes", "too_many")
    if len(set(ids)) != len(ids):
        raise _invalid("nodes.id", "duplicate")
    unique = _edges(values, ids)
    return {
        "slug": slug,
        "field": _member(values.get("field"), OPPORTUNITY_FIELDS, "field"),
        "title": _i18n(values.get("title"), "title", TITLE_MAX, required=True),
        "description": _i18n(
            values.get("description"), "description", DESCRIPTION_MAX, required=False
        ),
        "published": bool(values.get("published")),
        "stages": stages,
        "edges": unique,
    }


def required_ids(trajectory: Trajectory) -> set[str]:
    """Ids of the nodes that are not optional."""
    return {n.id for n in trajectory.nodes() if not n.optional}


def done_count(trajectory: Trajectory, progress: Mapping[str, str]) -> int:
    """Required nodes marked done."""
    return sum(1 for n in required_ids(trajectory) if progress.get(n) == "done")


def trajectory_of_dict(
    raw: Mapping[str, Any],
) -> tuple[tuple[Stage, ...], tuple[Edge, ...]]:
    """Stages and edges from their stored JSON (trusted, written by `to_json`)."""
    stages = tuple(
        Stage(
            id=s["id"],
            title=dict(s.get("title") or {}),
            nodes=tuple(
                Node(
                    id=n["id"],
                    title=dict(n.get("title") or {}),
                    kind=n["kind"],
                    level=n["level"],
                    description=dict(n.get("description") or {}),
                    optional=bool(n.get("optional")),
                    resources=tuple(
                        Resource(kind=r["kind"], ref=r["ref"], title=r["title"])
                        for r in n.get("resources") or ()
                    ),
                )
                for n in s.get("nodes") or ()
            ),
        )
        for s in raw.get("stages") or ()
    )
    edges = tuple(
        Edge(before=e["before"], after=e["after"]) for e in raw.get("edges") or ()
    )
    return stages, edges
