"""Mind map outputs (§ 3.4.2): a flat list of nodes with exactly one root.

Depth counts levels below the root: the root is level 0 and "Level 1" holds the main
concepts, so an overview has three levels below the root and a detailed map four.
"""

from collections import deque
from dataclasses import dataclass
from typing import Any, Final, Literal

from app.modules.notebooks.domain.artifacts.handler import (
    ArtifactHandler,
    ProcessContext,
    ProcessedOutput,
)
from app.modules.notebooks.domain.artifacts.kind_support import (
    CommonOptions,
    clean_text,
    clip_chars,
    dump_options,
    expect_options,
    fit_text,
    parse_options,
    require_list,
    validate_items,
)
from app.modules.notebooks.domain.artifacts.refs import build_refs_index, valid_refs
from app.modules.notebooks.domain.artifacts.strict import to_strict_schema
from app.modules.notebooks.domain.enums import ArtifactKind
from app.modules.notebooks.domain.errors import OutputInvalidError
from app.modules.notebooks.domain.limits import ARTIFACT_TITLE_MAX_CHARS
from app.modules.notebooks.domain.prompts.common import focus_clause

from pydantic import BaseModel, Field

SCHEMA_NAME: Final = "nb_mind_map"
MAX_TOKENS: Final = 6000  # up to 60 nodes with a one-sentence note each, in Cyrillic
MAX_DEPTH: Final = {"overview": 3, "detailed": 4}
MAX_NODES: Final = {"overview": 30, "detailed": 60}
MAX_CHILDREN: Final = 7
LABEL_MAX_CHARS: Final = 60
NOTE_MAX_CHARS: Final = 200
MAX_RAW_NODES: Final = 300


class MindMapOptions(CommonOptions):
    """`MindMapOptions` of § 4.4."""

    detail: Literal["overview", "detailed"] = "overview"


class MindMapNodeOut(BaseModel):
    """One node of the model's flat list."""

    id: str = Field(description="unique within the map, e.g. n1")
    parent_id: str | None = Field(description="id of the parent; null for the root")
    label: str = Field(description="short noun phrase, at most 6 words")
    note: str = Field(description="one sentence, at most 200 characters")
    refs: list[str] = Field(description='passage labels such as "S1:P3"')


class MindMapOutput(BaseModel):
    """The JSON of a mind map (``nb_mind_map``)."""

    title: str
    nodes: list[MindMapNodeOut] = Field(description="the root first, then the rest")


@dataclass(slots=True)
class _Node:
    id: str
    parent: str | None
    label: str
    note: str
    refs: list[str]


def _node_input(raw: Any) -> Any:
    """Fill what a model often leaves out so one sloppy field does not drop a node."""
    if not isinstance(raw, dict):
        return raw
    node = dict(raw)
    node["id"] = clean_text(str(node["id"])) if node.get("id") is not None else ""
    parent = node.get("parent_id")
    node["parent_id"] = str(parent) if parent not in (None, "") else None
    if node.get("note") is None:
        node["note"] = ""
    if not isinstance(node.get("refs"), list):
        node["refs"] = []
    return node


def _clean_nodes(items: list[MindMapNodeOut]) -> dict[str, _Node]:
    """Trim texts; drop nodes without id or label and repeated ids (first wins)."""
    nodes: dict[str, _Node] = {}
    for item in items:
        node_id = clean_text(item.id)
        label = fit_text(item.label, chars=LABEL_MAX_CHARS)
        if not node_id or not label or node_id in nodes:
            continue
        parent = clean_text(item.parent_id or "") or None
        nodes[node_id] = _Node(
            id=node_id,
            parent=None if parent == node_id else parent,
            label=label,
            note=fit_text(item.note, chars=NOTE_MAX_CHARS),
            refs=list(item.refs),
        )
    return nodes


def _single_root(nodes: dict[str, _Node]) -> str:
    """Keep the first root; any other root becomes its child."""
    roots = [node.id for node in nodes.values() if node.parent is None]
    if not roots:
        raise OutputInvalidError(
            ["there is no root: exactly one node must have parent_id null"]
        )
    for other in roots[1:]:
        nodes[other].parent = roots[0]
    return roots[0]


def _children(nodes: dict[str, _Node]) -> dict[str, list[str]]:
    children: dict[str, list[str]] = {}
    for node in nodes.values():
        if node.parent is not None:
            children.setdefault(node.parent, []).append(node.id)
    return children


def _reachable(nodes: dict[str, _Node], root: str) -> set[str]:
    children = _children(nodes)
    seen = {root}
    queue = deque([root])
    while queue:
        for child in children.get(queue.popleft(), []):
            if child not in seen:
                seen.add(child)
                queue.append(child)
    return seen


def _connect(nodes: dict[str, _Node], root: str) -> None:
    """Attach orphans to the root and break cycles so every node hangs on the root."""
    for node in nodes.values():
        if node.parent is not None and node.parent not in nodes:
            node.parent = root
    while True:
        reached = _reachable(nodes, root)
        loose = next((node for node in nodes.values() if node.id not in reached), None)
        if loose is None:
            return
        loose.parent = root


def _shape(nodes: dict[str, _Node], root: str, max_depth: int) -> dict[str, int]:
    """Depth of every node that survives the depth and children caps (root = 0)."""
    children = _children(nodes)
    depth = {root: 0}
    queue = deque([root])
    while queue:
        current = queue.popleft()
        if depth[current] >= max_depth:
            continue
        for child in children.get(current, [])[:MAX_CHILDREN]:
            depth[child] = depth[current] + 1
            queue.append(child)
    return depth


def _trim_to_cap(depth: dict[str, int], nodes: dict[str, _Node], cap: int) -> None:
    """Drop the deepest nodes first (the last of a level first) until ``cap`` fit."""
    position = {node_id: index for index, node_id in enumerate(nodes)}
    for node_id in sorted(depth, key=lambda i: (-depth[i], -position[i])):
        if len(depth) <= cap:
            return
        del depth[node_id]


def _preorder(nodes: dict[str, _Node], root: str, keep: set[str]) -> list[_Node]:
    """Parents before children, siblings in the model's order."""
    children = _children(nodes)
    ordered: list[_Node] = []
    stack = [root]
    while stack:
        current = stack.pop()
        ordered.append(nodes[current])
        stack.extend(reversed([c for c in children.get(current, []) if c in keep]))
    return ordered


class MindMapHandler:
    """Options, prompt, schema and validation of mind maps."""

    kind = ArtifactKind.MIND_MAP
    schema_name = SCHEMA_NAME

    def parse_options(self, raw: dict[str, Any]) -> MindMapOptions:
        """Validate the request's options."""
        return parse_options(MindMapOptions, raw)

    def stored_options(self, options: BaseModel) -> dict[str, Any]:
        """Options with defaults filled."""
        return dump_options(expect_options(options, MindMapOptions))

    def report_format(self, options: BaseModel) -> str | None:
        """Only reports have a format."""
        return None

    def max_tokens(self, options: BaseModel) -> int:
        """3 000 tokens."""
        return MAX_TOKENS

    def input_cap_tokens(self, studio_context_tokens: int) -> int:
        """The Studio context cap."""
        return studio_context_tokens

    def strict_schema(self) -> dict[str, Any]:
        """The strict JSON schema of the output."""
        return to_strict_schema(MindMapOutput)

    def task_block(self, options: BaseModel, prompt: str | None) -> str:
        """The English task (§ 3.4.2) plus the student's focus."""
        detail = expect_options(options, MindMapOptions).detail
        depth = MAX_DEPTH[detail]
        levels = f"{depth} levels" if detail == "overview" else f"up to {depth} levels"
        return (
            "Create a mind map of the main topic of the sources. The root node is the"
            " central topic (a clean noun phrase, never a heading copied verbatim)."
            " Level 1 has 4 to 7 main concepts; deeper levels hold sub-concepts, key"
            " facts, formulas and examples. Labels are short noun phrases of at most"
            " 6 words, never 'Detail' or 'Part 1'. Each `note` is one sentence (at"
            " most 200 characters) that explains the node to a student. Depth: "
            f"{levels} below the root; at most {MAX_CHILDREN} children per node; at"
            f" most {MAX_NODES[detail]} nodes. Give every node a unique `id` and set"
            " `parent_id` to the id of its parent (null for the root only). A node"
            " taken from the sources has refs; a node from your own knowledge has"
            f" empty refs.{focus_clause(prompt)}"
        )

    def default_title(self, notebook_title: str, options: BaseModel) -> str:
        """``Mind map: <notebook>``."""
        return clip_chars(f"Mind map: {notebook_title}", ARTIFACT_TITLE_MAX_CHARS)

    def process(
        self, data: dict[str, Any], options: BaseModel, ctx: ProcessContext
    ) -> ProcessedOutput:
        """Build one rooted tree within the caps and resolve every node's refs."""
        detail = expect_options(options, MindMapOptions).detail
        problems: list[str] = []
        raw = require_list(data, "nodes")[:MAX_RAW_NODES]
        items = validate_items(
            MindMapNodeOut, [_node_input(item) for item in raw], problems, "node"
        )
        nodes = _clean_nodes(items)
        if not nodes:
            raise OutputInvalidError(problems or ["`nodes` has no usable node"])
        root = _single_root(nodes)
        _connect(nodes, root)
        depth = _shape(nodes, root, MAX_DEPTH[detail])
        _trim_to_cap(depth, nodes, MAX_NODES[detail])
        ordered = _preorder(nodes, root, set(depth))
        refs = {node.id: valid_refs(node.refs, ctx.pack) for node in ordered}
        if not any(refs.values()):
            raise OutputInvalidError(
                ["no node has a valid ref: cite passage labels from <sources>"]
            )
        title = fit_text(data.get("title"), chars=ARTIFACT_TITLE_MAX_CHARS)
        content = {
            "title": title or nodes[root].label,
            "nodes": [
                {
                    "id": node.id,
                    "parent_id": node.parent,
                    "label": node.label,
                    "note": node.note,
                    "refs": refs[node.id],
                }
                for node in ordered
            ],
        }
        return ProcessedOutput(
            title=str(content["title"]),
            content=content,
            refs_index=build_refs_index(refs.values(), ctx.pack),
        )


HANDLER: ArtifactHandler = MindMapHandler()
