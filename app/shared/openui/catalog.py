"""The OpenUI component catalog shared with the web (`catalog.json`).

The same file is copied into `iht-web` (`packages/features-core/src/openui`), whose
renderer defines one React component per entry with the props in the same order:
OpenUI Lang maps positional arguments to props by that order.
"""

import json
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from typing import Any, Literal

Subset = Literal["chat", "studio"]
CATALOG_PATH = Path(__file__).with_name("catalog.json")


@dataclass(frozen=True, slots=True)
class PropType:
    """The type of one prop, list item or object field."""

    type: str  # string | number | text | enum | url | list | object | component
    values: tuple[str, ...] = ()  # enum
    of: "PropType | None" = None  # list
    fields: tuple["Prop", ...] = ()  # object
    max: int | None = None  # list


@dataclass(frozen=True, slots=True)
class Prop:
    """One named prop (or object field) with its type."""

    name: str
    kind: PropType
    required: bool = False


@dataclass(frozen=True, slots=True)
class Component:
    """One component the model may use."""

    name: str
    description: str
    subsets: frozenset[str]
    props: tuple[Prop, ...]


@dataclass(frozen=True, slots=True)
class Catalog:
    """Every allowed component and the limits of a block."""

    fence: str
    root: str
    limits: dict[str, int]
    link_schemes: tuple[str, ...]
    components: tuple[Component, ...] = field(default=())

    def component(self, name: str, subset: Subset) -> Component | None:
        """The component of that name when the subset allows it."""
        for item in self.components:
            if item.name == name and subset in item.subsets:
                return item
        return None

    def in_subset(self, subset: Subset) -> tuple[Component, ...]:
        """The components a subset allows."""
        return tuple(c for c in self.components if subset in c.subsets)


def _type(raw: dict[str, Any]) -> PropType:
    return PropType(
        type=str(raw["type"]),
        values=tuple(raw.get("values") or ()),
        of=_type(raw["of"]) if "of" in raw else None,
        fields=tuple(_prop(f) for f in raw.get("fields") or ()),
        max=raw.get("max"),
    )


def _prop(raw: dict[str, Any]) -> Prop:
    return Prop(str(raw["name"]), _type(raw), bool(raw.get("required", False)))


@cache
def load_catalog() -> Catalog:
    """Read `catalog.json` once."""
    raw = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    return Catalog(
        fence=raw["fence"],
        root=raw["root"],
        limits=dict(raw["limits"]),
        link_schemes=tuple(raw["link_schemes"]),
        components=tuple(
            Component(
                name=c["name"],
                description=c["description"],
                subsets=frozenset(c["subsets"]),
                props=tuple(_prop(p) for p in c["props"]),
            )
            for c in raw["components"]
        ),
    )
