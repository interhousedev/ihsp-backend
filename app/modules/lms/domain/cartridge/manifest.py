"""Parsing ``imsmanifest.xml`` of IMS Common Cartridge 1.0 to 1.3.

The manifest has metadata (the LOM title and description), one organization whose
root item holds the modules as nested items, and resources. An item points at a
resource with ``identifierref``; a resource has a type, an ``href``, its files and
dependencies on other resources. Paths are resolved against ``xml:base`` and
returned as archive member names.
"""

import posixpath
import xml.etree.ElementTree as ET  # noqa: N817
from dataclasses import dataclass, field
from typing import Final

from app.modules.lms.domain.cartridge.archive import resolve
from app.modules.lms.domain.cartridge.errors import CartridgeInvalidError
from app.modules.lms.domain.cartridge.xml_utils import (
    XML_BASE,
    child,
    children,
    descendants,
    local,
    lom_string,
    namespace,
    parse_xml,
    text_of,
)

_VERSIONS: Final = (
    ("imsccv1p3", "1.3"),
    ("imsccv1p2", "1.2"),
    ("imsccv1p1", "1.1"),
    ("imscc/", "1.0"),
)


@dataclass(frozen=True, slots=True)
class Resource:
    """One ``<resource>``: its type, entry file, files and dependencies."""

    identifier: str
    type: str
    href: str | None
    files: tuple[str, ...]
    dependencies: tuple[str, ...]
    base: str = ""

    @property
    def kind(self) -> str:
        """Return a short kind: webcontent, weblink, discussion, assessment, ..."""
        return resource_kind(self.type)


@dataclass(slots=True)
class Item:
    """One ``<item>`` of the organization: a folder or a pointer to a resource."""

    identifier: str
    title: str
    identifierref: str | None
    children: list["Item"] = field(default_factory=list)


@dataclass(slots=True)
class Manifest:
    """What the importer needs from the manifest."""

    version: str
    title: str
    description: str
    items: list[Item]
    resources: dict[str, Resource]


def resource_kind(resource_type: str) -> str:
    """Map a resource type (any CC version or Canvas) to a short kind."""
    value = resource_type.casefold()
    if value == "webcontent":
        return "webcontent"
    if value.startswith("imswl_"):
        return "weblink"
    if value.startswith("imsdt_"):
        return "discussion"
    if "question-bank" in value:
        return "question-bank"
    if "imsqti" in value or value.endswith("/assessment"):
        return "assessment"
    if "basiclti" in value or "imsblti" in value:
        return "lti"
    if "learning-application-resource" in value:
        return "associated"
    return "other"


def detect_version(root: ET.Element) -> str:
    """Return ``1.0``-``1.3`` from the namespace or schemaversion, else unknown."""
    ns = namespace(root.tag)
    for marker, version in _VERSIONS:
        if marker in ns:
            return version
    schema = text_of(child(root, "metadata", "schemaversion"))
    if schema[:3] in {"1.0", "1.1", "1.2", "1.3"}:
        return schema[:3]
    return "unknown"


def parse_manifest(data: bytes) -> Manifest:
    """Parse the manifest document.

    Raises:
        CartridgeInvalidError: ``bad-xml`` or ``bad-manifest`` (root is not a
            ``manifest``).
    """
    root = parse_xml(data, path="imsmanifest.xml")
    if local(root.tag) != "manifest":
        raise CartridgeInvalidError(params={"reason": "bad-manifest"})
    general = child(root, "metadata", "lom", "general")
    title = lom_string(child(general, "title"))
    description = lom_string(child(general, "description"))
    base = (root.get(XML_BASE) or "").strip("/")
    return Manifest(
        version=detect_version(root),
        title=title,
        description=description,
        items=_items(root),
        resources=_resources(root, base),
    )


def _items(root: ET.Element) -> list[Item]:
    organization = child(root, "organizations", "organization")
    if organization is None:
        return []
    top = [_item(node) for node in children(organization, "item")]
    # CC wraps the modules in one root item without a resource (``LearningModules``).
    if len(top) == 1 and top[0].identifierref is None:
        return top[0].children
    return top


def _item(node: ET.Element) -> Item:
    return Item(
        identifier=node.get("identifier", ""),
        title=text_of(child(node, "title")),
        identifierref=node.get("identifierref") or None,
        children=[_item(sub) for sub in children(node, "item")],
    )


def _resources(root: ET.Element, manifest_base: str) -> dict[str, Resource]:
    found: dict[str, Resource] = {}
    container = child(root, "resources")
    if container is None:
        return found
    for node in children(container, "resource"):
        identifier = node.get("identifier", "")
        if not identifier or identifier in found:
            continue
        base = resolve(manifest_base, node.get(XML_BASE) or "") or manifest_base
        files = []
        for file_node in descendants(node, "file"):
            path = resolve(base, file_node.get("href", ""))
            if path:
                files.append(path)
        href_raw = node.get("href")
        href = resolve(base, href_raw) if href_raw else None
        found[identifier] = Resource(
            identifier=identifier,
            type=node.get("type", ""),
            href=href or (files[0] if files else None),
            files=tuple(files),
            dependencies=tuple(
                dep.get("identifierref", "")
                for dep in children(node, "dependency")
                if dep.get("identifierref")
            ),
            base=base,
        )
    return found


def directory_of(path: str) -> str:
    """Return the directory part of a member path ('' for the root)."""
    return posixpath.dirname(path)
