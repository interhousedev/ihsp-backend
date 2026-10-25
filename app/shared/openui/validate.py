"""Validation of one OpenUI block against the catalog (the web renders the same set).

Besides the schema (known component, required props, types, list sizes) it applies
the safety rules: links are https only, strings never carry markup or script URLs.
"""

import re
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from app.shared.openui.catalog import Catalog, Prop, PropType, Subset, load_catalog
from app.shared.openui.lang import (
    Arr,
    Call,
    Lit,
    Node,
    Obj,
    OpenUiSyntaxError,
    Ref,
    parse_program,
)

MAX_DEPTH = 12
_UNSAFE_TEXT = re.compile(
    r"<\s*/?\s*(script|iframe|object|embed|style)|javascript:", re.I
)


@dataclass(slots=True)
class _Check:
    catalog: Catalog
    subset: Subset
    program: dict[str, Node]
    errors: list[str] = field(default_factory=list)

    def resolve(self, node: Node, where: str, depth: int) -> Node | None:
        seen: set[str] = set()
        while isinstance(node, Ref):
            if node.name in seen or node.name not in self.program:
                self.errors.append(
                    f"{where}: unknown or circular reference {node.name}"
                )
                return None
            seen.add(node.name)
            node = self.program[node.name]
        if depth > MAX_DEPTH:
            self.errors.append(f"{where}: nested too deeply")
            return None
        return node

    def component(self, node: Node, where: str, depth: int) -> None:
        found = self.resolve(node, where, depth)
        if found is None:
            return
        if not isinstance(found, Call):
            self.errors.append(f"{where}: expected a component call")
            return
        spec = self.catalog.component(found.name, self.subset)
        if spec is None:
            self.errors.append(f"{where}: component {found.name} is not allowed")
            return
        if len(found.args) > len(spec.props):
            self.errors.append(
                f"{found.name}: {len(found.args)} arguments, at most {len(spec.props)}"
            )
        for index, prop in enumerate(spec.props):
            arg = found.args[index] if index < len(found.args) else None
            self.prop(prop, arg, f"{found.name}.{prop.name}", depth + 1)

    def prop(self, prop: Prop, arg: Node | None, where: str, depth: int) -> None:
        value = None if arg is None else self.resolve(arg, where, depth)
        if value is None or (isinstance(value, Lit) and value.value is None):
            if prop.required and arg is not None and value is None:
                return  # the reference error is already reported
            if prop.required:
                self.errors.append(f"{where}: required prop is missing")
            return
        self.value(prop.kind, value, where, depth)

    def value(self, kind: PropType, node: Node, where: str, depth: int) -> None:
        if kind.type == "component":
            self.component(node, where, depth)
        elif kind.type == "list":
            self.list(kind, node, where, depth)
        elif kind.type == "object":
            self.obj(kind, node, where, depth)
        else:
            self.scalar(kind, node, where)

    def list(self, kind: PropType, node: Node, where: str, depth: int) -> None:
        if not isinstance(node, Arr) or kind.of is None:
            self.errors.append(f"{where}: expected an array")
            return
        limit = kind.max or self.catalog.limits["max_list_items"]
        if len(node.items) > limit:
            self.errors.append(f"{where}: {len(node.items)} items, at most {limit}")
        for index, item in enumerate(node.items):
            resolved = self.resolve(item, f"{where}[{index}]", depth)
            if resolved is not None:
                self.value(kind.of, resolved, f"{where}[{index}]", depth + 1)

    def obj(self, kind: PropType, node: Node, where: str, depth: int) -> None:
        if not isinstance(node, Obj):
            self.errors.append(f"{where}: expected an object")
            return
        entries = dict(node.entries)
        known = {f.name for f in kind.fields}
        for extra in sorted(set(entries) - known):
            self.errors.append(f"{where}: unknown field {extra}")
        for prop in kind.fields:
            self.prop(prop, entries.get(prop.name), f"{where}.{prop.name}", depth)

    def scalar(self, kind: PropType, node: Node, where: str) -> None:
        if not isinstance(node, Lit):
            self.errors.append(f"{where}: expected a {kind.type}")
            return
        value = node.value
        if kind.type == "number":
            ok = isinstance(value, float)
        elif kind.type == "text":
            ok = isinstance(value, (str, float)) and not isinstance(value, bool)
        elif kind.type == "enum":
            ok = value in kind.values
        else:  # string, url
            ok = isinstance(value, str)
        if not ok:
            self.errors.append(f"{where}: expected a {kind.type}")
            return
        if isinstance(value, str):
            self.text(kind, value, where)

    def text(self, kind: PropType, value: str, where: str) -> None:
        limit = self.catalog.limits["max_string_chars"]
        if len(value) > limit:
            self.errors.append(f"{where}: longer than {limit} characters")
        if kind.type == "url":
            parts = urlsplit(value)
            if parts.scheme not in self.catalog.link_schemes or not parts.netloc:
                self.errors.append(f"{where}: links must be absolute https URLs")
            elif re.search(r"\s", value):
                self.errors.append(f"{where}: a URL has no spaces")
        elif _UNSAFE_TEXT.search(value):
            self.errors.append(f"{where}: markup or script is not allowed")


def validate_block(source: str, subset: Subset = "chat") -> list[str]:
    """The problems of one block; an empty list means it can be rendered."""
    catalog = load_catalog()
    limits = catalog.limits
    if len(source) > limits["max_block_chars"]:
        return [f"block longer than {limits['max_block_chars']} characters"]
    try:
        program = parse_program(source)
    except (OpenUiSyntaxError, ValueError) as error:
        return [f"syntax: {error}"]
    if len(program) > limits["max_statements"]:
        return [f"more than {limits['max_statements']} statements"]
    if "root" not in program:
        return ["the block has no `root = ...` statement"]
    check = _Check(catalog, subset, program)
    check.component(program["root"], "root", 0)
    return check.errors[:20]
