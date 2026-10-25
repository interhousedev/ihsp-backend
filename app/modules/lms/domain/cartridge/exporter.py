"""Writing a course as an IMS Common Cartridge 1.3 and checking a cartridge offline.

Layout of the archive:

- ``imsmanifest.xml``: LOM title and description, one organization (a root item,
  one item per section, one per page, quiz and link), the resources;
- ``pages/<n>.html``: the text and cards of a step (webcontent);
- ``quizzes/<id>/assessment.xml``: one QTI 1.2 document per test block;
- ``links/<id>.xml``: one web link per video link block;
- ``web_resources/files/<file id>/<name>``: the files the steps use, each its own
  webcontent resource (how Canvas expects them);
- ``ihsp/course.json``: the exact step content for a lossless re-import into IHT
  (an associated-content resource that other platforms ignore).
"""

import html
import io
import json
import posixpath
import re
import zipfile
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Final
from uuid import UUID
from xml.sax.saxutils import escape, quoteattr

from app.modules.lms.domain.authoring.content_edit import FILE_REFERENCE
from app.modules.lms.domain.cartridge.archive import CartridgeArchive, resolve
from app.modules.lms.domain.cartridge.errors import CartridgeInvalidError
from app.modules.lms.domain.cartridge.html_markdown import markdown_to_html
from app.modules.lms.domain.cartridge.importer import (
    EXTENSION_FORMAT,
    EXTENSION_PATH,
    FILE_PREFIX,
)
from app.modules.lms.domain.cartridge.manifest import parse_manifest
from app.modules.lms.domain.cartridge.qti import write_qti
from app.modules.lms.domain.cartridge.xml_utils import (
    child,
    children,
    descendants,
    local,
    parse_xml,
)

CC13_NS: Final = "http://www.imsglobal.org/xsd/imsccv1p3/imscp_v1p1"
LOM_NS: Final = "http://ltsc.ieee.org/xsd/imsccv1p3/LOM/manifest"
LOMR_NS: Final = "http://ltsc.ieee.org/xsd/imsccv1p3/LOM/resource"
WL_NS: Final = "http://www.imsglobal.org/xsd/imsccv1p3/imswl_v1p3"
ASSESSMENT_TYPE: Final = "imsqti_xmlv1p2/imscc_xmlv1p3/assessment"
WEBLINK_TYPE: Final = "imswl_xmlv1p3"
ASSOCIATED_TYPE: Final = "associatedcontent/imscc_xmlv1p3/learning-application-resource"
VALID_TYPES: Final = frozenset(
    {
        "webcontent",
        ASSESSMENT_TYPE,
        WEBLINK_TYPE,
        ASSOCIATED_TYPE,
        "imsdt_xmlv1p3",
        "imsbasiclti_xmlv1p3",
        "imsqti_xmlv1p2/imscc_xmlv1p3/question-bank",
    }
)
_SAFE_NAME: Final = re.compile(r"[^A-Za-z0-9._-]+")


@dataclass(frozen=True, slots=True)
class ExportFile:
    """A stored file a step references."""

    name: str
    data: bytes


@dataclass(frozen=True, slots=True)
class ExportSection:
    """A section title and the draft content of its steps."""

    title: str
    steps: list[dict[str, Any]]


@dataclass(frozen=True, slots=True)
class ExportCourse:
    """What the exporter writes."""

    title: str
    description: str
    sections: list[ExportSection]
    files: dict[UUID, ExportFile]


@dataclass(slots=True)
class ExportResult:
    """The cartridge bytes and what could only be approximated."""

    data: bytes
    notes: list[str] = field(default_factory=list)


@dataclass(slots=True)
class _Resource:
    identifier: str
    type: str
    href: str
    files: list[str]
    dependencies: list[str] = field(default_factory=list)


class _Writer:
    def __init__(self, course: ExportCourse) -> None:
        self.course = course
        self.members: dict[str, bytes] = {}
        self.resources: list[_Resource] = []
        self.notes: list[str] = []
        self.file_paths: dict[UUID, str] = {}
        self.file_resources: dict[UUID, str] = {}
        self.counter = 0

    def next_id(self, prefix: str) -> str:
        self.counter += 1
        return f"{prefix}{self.counter:05d}"

    # - - - files - - -

    def file_path(self, file_id: UUID) -> str | None:
        if file_id in self.file_paths:
            return self.file_paths[file_id]
        stored = self.course.files.get(file_id)
        if stored is None:
            return None
        name = _SAFE_NAME.sub("_", stored.name).strip("._") or "file"
        path = f"web_resources/files/{file_id}/{name[:120]}"
        self.members[path] = stored.data
        identifier = self.next_id("F")
        self.resources.append(_Resource(identifier, "webcontent", path, [path]))
        self.file_paths[file_id] = path
        self.file_resources[file_id] = identifier
        return path

    def mapper(self, from_dir: str, used: set[str]) -> Callable[[str], str]:
        def url(value: str) -> str:
            match = FILE_REFERENCE.search(value)
            if not match or not value.startswith("/files/"):
                return value
            file_id = UUID(match.group(1))
            path = self.file_path(file_id)
            if path is None:
                self.notes.append(f"missing file {file_id}")
                return "#"
            used.add(self.file_resources[file_id])
            return posixpath.relpath(path, from_dir)

        return url

    # - - - steps - - -

    def step_items(self, number: int, content: dict[str, Any]) -> list[str]:
        title = str(content.get("title") or f"Step {number}")
        blocks = [b for b in content.get("blocks") or [] if isinstance(b, dict)]
        items: list[str] = []
        page_parts: list[str] = []
        used: set[str] = set()
        url = self.mapper("pages", used)
        extra: list[str] = []
        for block in blocks:
            kind = block.get("type")
            if kind == "text":
                page_parts.append(markdown_to_html(str(block.get("markdown", "")), url))
            elif kind == "flashcards":
                page_parts.append(_cards_html(block, url))
            elif kind == "video":
                extra.append(self.video(title, block, page_parts, used))
            elif kind == "test":
                extra.append(self.quiz(title, block))
            else:
                self.notes.append(f"{title}: block {kind} left out")
        if page_parts or not extra:
            path = f"pages/step_{number:04d}.html"
            body = "\n".join(page_parts)
            self.members[path] = _page(title, body).encode()
            identifier = self.next_id("R")
            self.resources.append(
                _Resource(identifier, "webcontent", path, [path], sorted(used))
            )
            items.append(_item(self.next_id("I"), title, identifier))
        items.extend(item for item in extra if item)
        return items

    def video(
        self, title: str, block: dict[str, Any], page: list[str], used: set[str]
    ) -> str:
        caption = str(block.get("caption") or title)
        if block.get("source") == "upload":
            path = self.file_path(UUID(str(block.get("file_id"))))
            if path is None:
                self.notes.append(f"{title}: video file missing")
                return ""
            used.add(self.file_resources[UUID(str(block["file_id"]))])
            href = html.escape(posixpath.relpath(path, "pages"))
            page.append(f'<p><a href="{href}">{html.escape(caption)}</a></p>')
            return ""
        link = str(block.get("url") or "")
        if not link:
            return ""
        identifier = self.next_id("L")
        path = f"links/{identifier}.xml"
        self.members[path] = (
            f'<?xml version="1.0" encoding="UTF-8"?>\n<webLink xmlns="{WL_NS}">'
            f"<title>{escape(caption)}</title>"
            f'<url href={quoteattr(link)} target="_blank"/></webLink>\n'
        ).encode()
        self.resources.append(_Resource(identifier, WEBLINK_TYPE, "", [path]))
        return _item(self.next_id("I"), caption, identifier)

    def quiz(self, title: str, block: dict[str, Any]) -> str:
        identifier = self.next_id("Q")
        path = f"quizzes/{identifier}/assessment.xml"
        used: set[str] = set()
        url = self.mapper(f"quizzes/{identifier}", used)
        document, changed = write_qti(
            identifier, title, block, lambda md: markdown_to_html(md, url)
        )
        if changed:
            self.notes.append(f"{title}: {changed} question(s) exported as essay")
        self.members[path] = document.encode()
        self.resources.append(
            _Resource(identifier, ASSESSMENT_TYPE, "", [path], sorted(used))
        )
        return _item(self.next_id("I"), title, identifier)

    # - - - course - - -

    def extension(self) -> None:  # noqa: C901
        def swap(value: Any) -> Any:  # noqa: ANN401 - JSON
            if isinstance(value, str):
                return FILE_REFERENCE.sub(lambda m: self._file_ref(m.group(1)), value)
            if isinstance(value, list):
                return [swap(v) for v in value]
            if isinstance(value, dict):
                return {k: swap(v) for k, v in value.items() if k != "id"}
            return value

        sections = []
        for section in self.course.sections:
            steps = []
            for content in section.steps:
                blocks = []
                for block in content.get("blocks") or []:
                    if block.get("type") == "video" and block.get("source") == "upload":
                        ref = self._file_ref(str(block.get("file_id")))
                        caption = block.get("caption") or "Video"
                        blocks.append(
                            {"type": "text", "markdown": f"[{caption}]({ref})"}
                        )
                    else:
                        blocks.append(swap(block))
                steps.append({"title": content.get("title", ""), "blocks": blocks})
            sections.append({"title": section.title, "steps": steps})
        data = {
            "format": EXTENSION_FORMAT,
            "title": self.course.title,
            "description": self.course.description,
            "sections": sections,
        }
        self.members[EXTENSION_PATH] = json.dumps(
            data, ensure_ascii=False, indent=1
        ).encode()
        identifier = self.next_id("X")
        self.resources.append(
            _Resource(identifier, ASSOCIATED_TYPE, EXTENSION_PATH, [EXTENSION_PATH])
        )

    def _file_ref(self, raw: str) -> str:
        try:
            path = self.file_path(UUID(raw))
        except ValueError:
            path = None
        return f"{FILE_PREFIX}{path}" if path else "#"

    def write(self) -> ExportResult:
        organization: list[str] = []
        number = 0
        for section in self.course.sections:
            inner: list[str] = []
            for content in section.steps:
                number += 1
                inner.extend(self.step_items(number, content))
            organization.append(
                f'<item identifier="{self.next_id("S")}">'
                f"<title>{escape(section.title)}</title>{''.join(inner)}</item>"
            )
        self.extension()
        manifest = _manifest(self.course, organization, self.resources)
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("imsmanifest.xml", manifest)
            for path, data in self.members.items():
                archive.writestr(path, data)
        return ExportResult(buffer.getvalue(), self.notes)


def export_cartridge(course: ExportCourse) -> ExportResult:
    """Write the course as a Common Cartridge 1.3 archive."""
    return _Writer(course).write()


def _item(identifier: str, title: str, ref: str) -> str:
    return (
        f'<item identifier="{identifier}" identifierref="{ref}">'
        f"<title>{escape(title)}</title></item>"
    )


def _page(title: str, body: str) -> str:
    return (
        '<!DOCTYPE html>\n<html><head><meta charset="utf-8"/>'
        f"<title>{html.escape(title)}</title></head>\n<body>\n{body}\n</body></html>\n"
    )


def _cards_html(block: dict[str, Any], url: Callable[[str], str]) -> str:
    rows = "".join(
        f"<dt>{markdown_to_html(str(c.get('front', '')), url)}</dt>"
        f"<dd>{markdown_to_html(str(c.get('back', '')), url)}</dd>"
        for c in block.get("cards") or []
    )
    return f"<dl>{rows}</dl>"


def _manifest(
    course: ExportCourse, organization: list[str], resources: list[_Resource]
) -> str:
    resource_xml = []
    for resource in resources:
        href = f" href={quoteattr(resource.href)}" if resource.href else ""
        files = "".join(f"<file href={quoteattr(f)}/>" for f in resource.files)
        deps = "".join(
            f'<dependency identifierref="{d}"/>' for d in resource.dependencies
        )
        resource_xml.append(
            f'<resource identifier="{resource.identifier}" type="{resource.type}"{href}>'  # noqa: E501
            f"{files}{deps}</resource>"
        )
    description = (
        f"<lomimscc:description><lomimscc:string>{escape(course.description)}"
        "</lomimscc:string></lomimscc:description>"
        if course.description
        else ""
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<manifest identifier="ihsp_course" xmlns="{CC13_NS}" '
        f'xmlns:lomimscc="{LOM_NS}" xmlns:lom="{LOMR_NS}" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
        f'xsi:schemaLocation="{CC13_NS} http://www.imsglobal.org/profile/cc/ccv1p3/'
        'ccv1p3_imscp_v1p2_v1p0.xsd">'
        "<metadata><schema>IMS Common Cartridge</schema>"
        "<schemaversion>1.3.0</schemaversion><lomimscc:lom><lomimscc:general>"
        f"<lomimscc:title><lomimscc:string>{escape(course.title)}</lomimscc:string>"
        f"</lomimscc:title>{description}</lomimscc:general></lomimscc:lom></metadata>"
        '<organizations><organization identifier="ORG" structure="rooted-hierarchy">'
        f'<item identifier="ROOT">{"".join(organization)}</item>'
        "</organization></organizations>"
        f"<resources>{''.join(resource_xml)}</resources></manifest>\n"
    )


def validate_cartridge(data: bytes) -> list[str]:  # noqa: C901 - a list of checks
    """Check a cartridge the way an LMS would; return the problems (empty: valid).

    Checks: the zip opens safely, the manifest parses, it is CC 1.3 with
    schemaversion 1.3.0, identifiers are unique, every ``identifierref`` and
    dependency names a resource, every ``href`` and ``file`` exists, every member is
    listed by a resource, resource types are CC 1.3 types, webcontent and
    associated resources have an href, and every XML member parses.
    """
    problems: list[str] = []
    try:
        archive = CartridgeArchive(data)
    except CartridgeInvalidError as exc:
        return [f"archive: {exc.params.get('reason')}"]
    raw = archive.read("imsmanifest.xml")
    root = parse_xml(raw, path="imsmanifest.xml")
    manifest = parse_manifest(raw)
    if manifest.version != "1.3":
        problems.append(f"version {manifest.version}")
    if (child(root, "metadata", "schemaversion") is None) or (
        "".join(child(root, "metadata", "schemaversion").itertext()).strip() != "1.3.0"  # type: ignore[union-attr]  # noqa: E501
    ):
        problems.append("schemaversion is not 1.3.0")
    ids: list[str] = []
    refs: list[str] = []
    for node in root.iter():
        name = local(node.tag)
        if name in {"item", "resource", "organization", "manifest"} and node.get(
            "identifier"
        ):
            ids.append(node.get("identifier", ""))
        if name == "item" and node.get("identifierref"):
            refs.append(node.get("identifierref", ""))
        if name == "dependency":
            refs.append(node.get("identifierref", ""))
    duplicates = sorted({i for i in ids if ids.count(i) > 1})
    if duplicates:
        problems.append(f"duplicate identifiers: {', '.join(duplicates[:5])}")
    for ref in refs:
        if ref not in manifest.resources:
            problems.append(f"unknown identifierref {ref}")
    listed: set[str] = set()
    container = child(root, "resources")
    for node in children(container, "resource") if container is not None else []:
        rtype = node.get("type", "")
        if rtype not in VALID_TYPES:
            problems.append(f"resource type {rtype}")
        href = node.get("href")
        if rtype in {"webcontent", ASSOCIATED_TYPE} and not href:
            problems.append(f"{node.get('identifier')}: no href")
        files = [f.get("href", "") for f in descendants(node, "file")]
        if href and href not in files:
            problems.append(f"{node.get('identifier')}: href not among its files")
        for path in sorted({*files, *([href] if href else [])}):
            clean = resolve("", path)
            if clean is None or clean not in archive.names:
                problems.append(f"missing file {path}")
            else:
                listed.add(clean)
    for name in archive.names:
        if name != "imsmanifest.xml" and name not in listed:
            problems.append(f"unlisted file {name}")
        if name.endswith(".xml"):
            try:
                parse_xml(archive.read(name), path=name)
            except CartridgeInvalidError:
                problems.append(f"bad xml {name}")
    return problems
