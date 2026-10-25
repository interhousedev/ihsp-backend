"""Planning an import: a cartridge archive to sections, steps and the files they use.

Mapping:

- the organization's top-level items (Canvas modules, OpenStax chapters) become
  sections; the resources under them, at any depth, become steps in order. Items
  at the top that point straight at a resource go to a first section named after
  the course.
- ``webcontent`` HTML pages become text blocks (plus video blocks for YouTube or
  Vimeo iframes); other files become a link or an image to the uploaded file.
- web links become a link (or a video block); discussions a text block; QTI
  assessments a test block; LTI links a link. Question banks, unknown types and
  missing files are listed in the report.
- pages, quizzes and discussions no item points at go to an "Other materials"
  section, so a cartridge without modules still imports its content.

Asset references are written as ``ihsp-asset:<n>`` (an index into
``ImportPlan.assets``); the application uploads the files and swaps in
``/files/<id>``. A cartridge exported by IHT carries ``ihsp/course.json`` with the
exact step content, which is used instead of the HTML when it is valid.
"""

import json
import mimetypes
import posixpath
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any, Final

from app.modules.lms.domain.cartridge.archive import CartridgeArchive, resolve
from app.modules.lms.domain.cartridge.errors import CartridgeInvalidError
from app.modules.lms.domain.cartridge.html_markdown import (
    UrlKind,
    html_to_markdown,
)
from app.modules.lms.domain.cartridge.manifest import (
    Item,
    Manifest,
    Resource,
    directory_of,
    parse_manifest,
)
from app.modules.lms.domain.cartridge.qti import parse_qti
from app.modules.lms.domain.cartridge.xml_utils import (
    child,
    descendants,
    parse_xml,
    text_of,
)

EXTENSION_PATH: Final = "ihsp/course.json"
EXTENSION_FORMAT: Final = "ihsp-course/1"
ASSET_PREFIX: Final = "ihsp-asset:"
FILE_PREFIX: Final = "ihsp-file:"  # an archive path inside ihsp/course.json
MAX_SECTIONS: Final = 200
MAX_STEPS: Final = 2000
MAX_MARKDOWN: Final = 200_000
MAX_TITLE: Final = 200
OTHER_SECTION: Final = "Other materials"
_FILEBASE: Final = re.compile(
    r"^(\$|%24)IMS[-_]CC[-_]FILEBASE(\$|%24)/?", re.IGNORECASE
)
_CANVAS_REF: Final = re.compile(
    r"^(\$|%24)(WIKI_REFERENCE|CANVAS_OBJECT_REFERENCE|CANVAS_COURSE_REFERENCE)",
    re.IGNORECASE,
)
_VIDEO_HOSTS: Final = re.compile(r"(youtube\.com|youtu\.be|vimeo\.com)", re.I)
_HTML: Final = (".html", ".htm", ".xhtml")
_SKIP_DIRS: Final = ("web_resources/", "course_settings/", "non_cc_assessments/")


@dataclass(slots=True)
class ReportItem:
    """Something kept only partly (as a link or note) or skipped."""

    title: str
    kind: str
    note: str


@dataclass(slots=True)
class ImportReport:
    """What the import made and what it could not map."""

    title: str = ""
    sections: int = 0
    steps: int = 0
    files: int = 0
    quizzes: int = 0
    questions: int = 0
    links: int = 0
    items: list[ReportItem] = field(default_factory=list)

    def note(self, title: str, kind: str, note: str) -> None:
        """Add an entry (at most 500 are kept)."""
        if len(self.items) < 500:
            self.items.append(ReportItem(title[:MAX_TITLE], kind, note[:300]))


@dataclass(slots=True)
class PlannedStep:
    """A step: title and blocks as ``StepContent`` dicts (assets as placeholders)."""

    title: str
    blocks: list[dict[str, Any]]


@dataclass(slots=True)
class PlannedSection:
    """A section and its steps."""

    title: str
    steps: list[PlannedStep] = field(default_factory=list)


@dataclass(slots=True)
class ImportPlan:
    """Everything the application needs to create the course."""

    title: str
    description: str
    version: str
    sections: list[PlannedSection]
    assets: list[str]
    report: ImportReport


def clean_title(title: str, fallback: str = "Untitled") -> str:
    """Collapse spaces and cut to 200 characters."""
    text = " ".join(title.split())[:MAX_TITLE].strip()
    return text or fallback


def plan_import(archive: CartridgeArchive) -> ImportPlan:
    """Read the manifest and plan the course.

    Raises:
        CartridgeInvalidError: Broken manifest, or nothing to import.
    """
    manifest = parse_manifest(archive.read("imsmanifest.xml"))
    planner = _Planner(archive, manifest)
    plan = planner.from_extension() or planner.plan()
    if not any(section.steps for section in plan.sections):
        raise CartridgeInvalidError(params={"reason": "empty"})
    report = plan.report
    report.title = plan.title
    report.sections = len(plan.sections)
    report.steps = sum(len(s.steps) for s in plan.sections)
    report.files = len(plan.assets)
    return plan


class _Planner:
    def __init__(self, archive: CartridgeArchive, manifest: Manifest) -> None:
        self.archive = archive
        self.manifest = manifest
        self.report = ImportReport()
        self.assets: list[str] = []
        self.asset_index: dict[str, int] = {}
        self.used: set[str] = set()
        self.step_count = 0
        self.page_paths = {
            r.href
            for r in manifest.resources.values()
            if r.kind == "webcontent" and r.href and r.href.lower().endswith(_HTML)
        }

    # - - - the course - - -

    def plan(self) -> ImportPlan:  # noqa: C901
        title = self.manifest.title or self._canvas_title() or "Imported course"
        items = self.manifest.items or self._module_meta_items()
        sections: list[PlannedSection] = []
        loose = PlannedSection(clean_title(title))
        for item in items:
            if item.children:
                section = PlannedSection(clean_title(item.title, "Section"))
                for leaf in _leaves(item):
                    self._add(section, leaf)
                if item.identifierref:
                    self._add(
                        section, Item(item.identifier, item.title, item.identifierref)
                    )
                sections.append(section)
            elif item.identifierref:
                self._add(loose, item)
            else:
                self.report.note(item.title, "subheader", "a heading without content")
        if loose.steps:
            sections.insert(0, loose)
        other = PlannedSection(OTHER_SECTION)
        for resource in self._unreferenced():
            self._add(other, Item(resource.identifier, "", resource.identifier))
        if other.steps:
            sections.append(other)
        if len(sections) > MAX_SECTIONS:
            self.report.note(title, "course", f"only the first {MAX_SECTIONS} sections")
            sections = sections[:MAX_SECTIONS]
        sections = [s for s in sections if s.steps or s.title]
        return ImportPlan(
            title=clean_title(title, "Imported course"),
            description=self.manifest.description[:5000],
            version=self.manifest.version,
            sections=sections,
            assets=self.assets,
            report=self.report,
        )

    def _canvas_title(self) -> str:
        path = self.archive.find("course_settings/course_settings.xml")
        if path is None:
            return ""
        root = parse_xml(self.archive.read(path), path=path)
        return text_of(child(root, "title"))

    def _module_meta_items(self) -> list[Item]:
        """Canvas ``module_meta.xml`` when the organization is empty."""
        path = self.archive.find("course_settings/module_meta.xml")
        if path is None:
            return []
        root = parse_xml(self.archive.read(path), path=path)
        modules = []
        for module in descendants(root, "module"):
            entries = []
            for entry in descendants(module, "item"):
                ref = text_of(child(entry, "identifierref")) or None
                entries.append(
                    Item(
                        entry.get("identifier", ""), text_of(child(entry, "title")), ref
                    )
                )
            modules.append(
                Item(
                    module.get("identifier", ""),
                    text_of(child(module, "title")),
                    None,
                    entries,
                )
            )
        return modules

    def _unreferenced(self) -> Iterator[Resource]:  # noqa: C901
        referenced: set[str] = set()
        stack = list(self.manifest.items)
        while stack:
            item = stack.pop()
            if item.identifierref:
                referenced.add(item.identifierref)
            stack.extend(item.children)
        for resource in self.manifest.resources.values():
            referenced.update(resource.dependencies)
        for resource in self.manifest.resources.values():
            if resource.identifier in referenced:
                continue
            href = resource.href or ""
            if resource.kind == "webcontent":
                if not href.lower().endswith(_HTML) or href.startswith(_SKIP_DIRS):
                    continue
                if href in self.used:
                    continue
            elif resource.kind not in {"assessment", "discussion", "weblink"}:
                continue
            yield resource

    # - - - steps - - -

    def _add(self, section: PlannedSection, item: Item) -> None:
        if self.step_count >= MAX_STEPS:
            if self.step_count == MAX_STEPS:
                self.report.note(
                    item.title, "course", f"only the first {MAX_STEPS} steps"
                )
                self.step_count += 1
            return
        resource = self.manifest.resources.get(item.identifierref or "")
        if resource is None:
            self.report.note(item.title, "missing", "the item points at no resource")
            return
        step = self._step(item.title, resource)
        if step is not None:
            section.steps.append(step)
            self.step_count += 1

    def _step(self, title: str, resource: Resource) -> PlannedStep | None:  # noqa: C901
        kind = resource.kind
        if kind == "webcontent":
            return self._webcontent(title, resource)
        if kind == "weblink":
            return self._weblink(title, resource)
        if kind == "discussion":
            return self._discussion(title, resource)
        if kind == "assessment":
            return self._assessment(title, resource)
        if kind == "lti":
            return self._lti(title, resource)
        if kind == "associated":
            qti = next((f for f in resource.files if f.lower().endswith(".qti")), None)
            if qti:
                return self._assessment(title, resource, qti)
            page = next((f for f in resource.files if f.lower().endswith(_HTML)), None)
            if page:
                return self._webcontent(title, resource, page)
        if kind == "question-bank":
            self.report.note(
                title or resource.identifier, kind, "question banks are not imported"
            )
            return None
        self.report.note(
            title or resource.identifier, resource.type or kind, "unsupported type"
        )
        files = [f for f in resource.files if self.archive.find(f)]
        if not files:
            return None
        links = "\n".join(self._file_link(f) for f in files)
        return PlannedStep(clean_title(title or resource.identifier), [_text(links)])

    def _webcontent(
        self, title: str, resource: Resource, href: str | None = None
    ) -> PlannedStep | None:
        path = self.archive.find(href or resource.href)
        if path is None:
            self.report.note(title or resource.identifier, "webcontent", "file missing")
            return None
        if not path.lower().endswith(_HTML):
            return PlannedStep(
                clean_title(title or posixpath.basename(path)),
                [_text(self._file_link(path))],
            )
        conversion = html_to_markdown(
            self.archive.read_text(path),
            lambda url, kind: self._rewrite(url, kind, path, resource),
        )
        blocks = (
            [_text(self._cap(conversion.markdown, title))]
            if conversion.markdown
            else []
        )
        blocks += [_video(url) for url in conversion.videos]
        return PlannedStep(
            clean_title(title or conversion.title or posixpath.basename(path)), blocks
        )

    def _weblink(self, title: str, resource: Resource) -> PlannedStep | None:
        root = self._xml(resource)
        if root is None:
            self.report.note(title or resource.identifier, "weblink", "file missing")
            return None
        url_node = next(descendants(root, "url"), None)
        url = (url_node.get("href", "") if url_node is not None else "").strip()
        name = clean_title(title or text_of(child(root, "title")) or url)
        if not url.startswith(("http://", "https://")):
            self.report.note(name, "weblink", "no usable URL")
            return None
        self.report.links += 1
        if _VIDEO_HOSTS.search(url):
            return PlannedStep(name, [_video(url)])
        return PlannedStep(name, [_text(f"[{_label(name)}]({url})")])

    def _discussion(self, title: str, resource: Resource) -> PlannedStep | None:
        root = self._xml(resource)
        if root is None:
            self.report.note(title or resource.identifier, "discussion", "file missing")
            return None
        path = self.archive.find(resource.href) or ""
        name = clean_title(title or text_of(child(root, "title")), "Discussion")
        body_node = child(root, "text")
        body = html_to_markdown(
            text_of(body_node) if body_node is not None else "",
            lambda url, kind: self._rewrite(url, kind, path, resource),
        ).markdown
        links = []
        for attachment in descendants(root, "attachment"):
            target = self._locate(attachment.get("href", ""), path, resource)
            if target:
                links.append(self._file_link(target))
        markdown = "\n\n".join(
            p for p in ["**Discussion**", body, "\n".join(links)] if p
        )
        self.report.note(name, "discussion", "imported as a text step")
        return PlannedStep(name, [_text(self._cap(markdown, name))])

    def _assessment(
        self, title: str, resource: Resource, path: str | None = None
    ) -> PlannedStep | None:
        candidates = [path] if path else [resource.href, *resource.files]
        found = None
        for candidate in candidates:
            member = self.archive.find(candidate)
            if member and not member.endswith("assessment_meta.xml"):
                found = member
                break
        if found is None:
            self.report.note(title or resource.identifier, "assessment", "file missing")
            return None
        quiz = parse_qti(
            self.archive.read(found),
            path=found,
            convert=lambda raw: html_to_markdown(
                raw, lambda url, kind: self._rewrite(url, kind, found, resource)
            ).markdown,
        )
        name = clean_title(title or quiz.title, "Quiz")
        for note in quiz.notes:
            self.report.note(name, "question", note)
        questions = quiz.block["questions"]
        if not questions:
            self.report.note(name, "assessment", "no supported questions")
            return None
        self.report.quizzes += 1
        self.report.questions += len(questions)
        return PlannedStep(name, [quiz.block])

    def _lti(self, title: str, resource: Resource) -> PlannedStep | None:
        root = self._xml(resource)
        url = ""
        name = title
        if root is not None:
            name = title or text_of(child(root, "title"))
            for tag in ("secure_launch_url", "launch_url"):
                node = next(descendants(root, tag), None)
                if node is not None and text_of(node):
                    url = text_of(node)
                    break
        name = clean_title(name or resource.identifier, "External tool")
        self.report.note(name, "lti", "external tool kept as a link")
        if not url.startswith(("http://", "https://")):
            return None
        self.report.links += 1
        return PlannedStep(name, [_text(f"[{_label(name)}]({url})")])

    # - - - files and URLs - - -

    def _xml(self, resource: Resource) -> Any:  # noqa: ANN401 - an Element or None
        candidates = [resource.href, *resource.files]
        for candidate in candidates:
            member = self.archive.find(candidate)
            if member and member.lower().endswith(".xml"):
                return parse_xml(self.archive.read(member), path=member)
        return None

    def _locate(self, url: str, page: str, resource: Resource) -> str | None:
        raw = url.strip()
        match = _FILEBASE.match(raw)
        bases = [directory_of(page), resource.base, "web_resources", ""]
        if match:
            raw = raw[match.end() :]
            bases = [resource.base, "web_resources", directory_of(page), ""]
        for base in bases:
            target = resolve(base, raw)
            member = self.archive.find(target)
            if member:
                return member
        return None

    def _rewrite(
        self, url: str, kind: UrlKind, page: str, resource: Resource
    ) -> str | None:
        raw = url.strip()
        lower = raw.lower()
        if not raw or _CANVAS_REF.match(raw):
            return None
        if lower.startswith(("http://", "https://", "mailto:")):
            return raw
        if raw.startswith("//"):
            return "https:" + raw
        if ":" in lower.split("/", 1)[0] and not _FILEBASE.match(raw):
            return None  # data:, javascript:, ftp:, other schemes
        member = self._locate(raw, page, resource)
        if member is None:
            self.report.note(
                posixpath.basename(raw)[:100] or raw[:100],
                "file",
                f"missing: {raw[:200]}",
            )
            return None
        if member in self.page_paths and kind == "link":
            return None  # a link to another page of the course: keep the text
        return self._asset(member)

    def _asset(self, member: str) -> str:
        self.used.add(member)
        index = self.asset_index.get(member)
        if index is None:
            index = len(self.assets)
            self.assets.append(member)
            self.asset_index[member] = index
        return f"{ASSET_PREFIX}{index}"

    def _file_link(self, member: str) -> str:
        name = posixpath.basename(member)
        url = self._asset(member)
        kind = mimetypes.guess_type(name)[0] or ""
        if kind.startswith("image/"):
            return f"![{_label(name)}]({url})"
        return f"[{_label(name)}]({url})"

    def _cap(self, markdown: str, title: str) -> str:
        if len(markdown) <= MAX_MARKDOWN:
            return markdown
        self.report.note(title, "webcontent", "a very long page was shortened")
        return markdown[:MAX_MARKDOWN]

    # - - - the IHT extension - - -

    def from_extension(self) -> ImportPlan | None:  # noqa: C901
        path = self.archive.find(EXTENSION_PATH)
        if path is None:
            return None
        try:
            data = json.loads(self.archive.read_text(path))
        except ValueError:
            return None
        if not isinstance(data, dict) or data.get("format") != EXTENSION_FORMAT:
            return None
        sections = []
        for section in data.get("sections") or []:
            planned = PlannedSection(
                clean_title(str(section.get("title", "")), "Section")
            )
            for step in section.get("steps") or []:
                content = self._swap_files(step)
                if not isinstance(content, dict):
                    continue
                blocks = [b for b in content.get("blocks") or [] if isinstance(b, dict)]
                for block in blocks:
                    if block.get("type") == "test":
                        self.report.quizzes += 1
                        self.report.questions += len(block.get("questions") or [])
                planned.steps.append(
                    PlannedStep(clean_title(str(content.get("title", ""))), blocks)
                )
            sections.append(planned)
        return ImportPlan(
            title=clean_title(str(data.get("title", "")), "Imported course"),
            description=str(data.get("description", ""))[:5000],
            version=self.manifest.version,
            sections=sections[:MAX_SECTIONS],
            assets=self.assets,
            report=self.report,
        )

    def _swap_files(self, value: Any) -> Any:  # noqa: ANN401 - JSON
        if isinstance(value, str):
            return re.sub(
                re.escape(FILE_PREFIX) + r"([^)\s\"]+)",
                lambda m: self._swap_one(m.group(1)),
                value,
            )
        if isinstance(value, list):
            return [self._swap_files(v) for v in value]
        if isinstance(value, dict):
            return {k: self._swap_files(v) for k, v in value.items()}
        return value

    def _swap_one(self, path: str) -> str:
        member = self.archive.find(resolve("", path))
        if member is None:
            self.report.note(path[:100], "file", "missing in the cartridge")
            return "#"
        return self._asset(member)


def _leaves(item: Item) -> Iterator[Item]:
    for sub in item.children:
        if sub.identifierref:
            yield sub
        yield from _leaves(sub)


def _text(markdown: str) -> dict[str, Any]:
    return {"type": "text", "markdown": markdown}


def _video(url: str) -> dict[str, Any]:
    return {"type": "video", "source": "link", "url": url[:2000]}


def _label(text: str) -> str:
    return re.sub(r"([\[\]\\])", r"\\\1", text)
