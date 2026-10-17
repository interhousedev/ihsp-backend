"""Find the files and article images a web page offers (stdlib `html.parser`).

Documents (PDF, DOCX, PPTX, XLSX) and audio are taken from links anywhere outside
the page chrome (header, nav, footer, aside, forms); images only from the article
body when the page has one. Icons, logos, trackers, ads, data URIs, SVG and images
declared smaller than `min_image_px` are skipped. Only http(s) URLs on the page's own
site or a reputable one (education, government, open archives) are kept.
"""

import re
from dataclasses import dataclass
from html.parser import HTMLParser
from posixpath import basename
from urllib.parse import unquote, urljoin, urlsplit, urlunsplit

from app.modules.notebooks.ports.web_materials import MaterialCandidate, MaterialKind

DOCUMENT_EXTENSIONS = frozenset({".pdf", ".docx", ".pptx", ".xlsx"})
AUDIO_EXTENSIONS = frozenset({".mp3", ".m4a", ".ogg", ".wav"})
IMAGE_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg", ".webp"})
CONTEXT_CHARS = 300
TITLE_CHARS = 200
CHROME_TAGS = frozenset({"header", "nav", "footer", "aside", "form", "noscript"})
ARTICLE_TAGS = frozenset({"article", "main"})
RAW_TAGS = frozenset({"script", "style", "template", "svg"})
VOID_TAGS = frozenset(
    {"img", "br", "hr", "meta", "link", "input", "source", "wbr", "area", "col"}
)
_JUNK = re.compile(
    r"logo|icon|favicon|avatar|sprite|badge|banner|emoji|button|pixel|spacer|"
    r"tracking|tracker|analytics|doubleclick|advert|\bads?\b|/ads?/|adserver|"
    r"facebook\.com/tr|gravatar",
    re.IGNORECASE,
)
_REPUTABLE_SUFFIXES = (
    ".edu",
    ".gov",
    ".edu.uz",
    ".gov.uz",
    ".ac.uk",
    ".ac.uz",
    ".europa.eu",
    ".int",
    "wikipedia.org",
    "wikimedia.org",
    "arxiv.org",
    "openstax.org",
    "khanacademy.org",
    "unesco.org",
    "who.int",
    "nasa.gov",
)
_SPACES = re.compile(r"\s+")


def _extension(url: str) -> str:
    name = basename(urlsplit(url).path).lower()
    dot = name.rfind(".")
    return name[dot:] if dot >= 0 else ""


def _site(host: str) -> str:
    """The registrable part of a host, roughly (the last two labels)."""
    labels = host.lower().rstrip(".").split(".")
    return ".".join(labels[-2:])


def reputable(host: str, page_host: str) -> bool:
    """The page's own site, or an education, government or open-archive host."""
    host = host.lower()
    if _site(host) == _site(page_host):
        return True
    return host.endswith(_REPUTABLE_SUFFIXES)


def _absolute(base: str, raw: str) -> str | None:
    raw = raw.strip()
    if not raw or raw.lower().startswith(("data:", "javascript:", "mailto:", "blob:")):
        return None
    try:
        parts = urlsplit(urljoin(base, raw))
    except ValueError:
        return None
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return None
    return urlunsplit(parts._replace(fragment=""))


def _px(value: str | None) -> int | None:
    match = re.match(r"\s*(\d+)", value or "")
    return int(match.group(1)) if match else None


def _clean(text: str, limit: int) -> str:
    return _SPACES.sub(" ", text).strip()[:limit]


@dataclass(slots=True)
class _Found:
    url: str
    kind: MaterialKind
    title: str
    context: str
    in_article: bool


@dataclass(slots=True)
class _OpenLink:
    url: str
    kind: MaterialKind
    before: str
    text: list[str]


class _Scanner(HTMLParser):
    def __init__(self, base: str, min_image_px: int) -> None:
        super().__init__(convert_charrefs=True)
        self.base = base
        self.min_image_px = min_image_px
        self.stack: list[str] = []
        self.chrome = 0
        self.article = 0
        self.skip = 0  # script/style
        self.recent = ""
        self.link: _OpenLink | None = None
        self.found: list[_Found] = []
        self.caption_for: _Found | None = None

    # - - - Tags - - -

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {name: value or "" for name, value in attrs}
        self._push(tag, values)
        if self.chrome or self.skip:
            return
        if tag == "a":
            self._close_link()  # an unclosed link ends where the next one starts
            self._open_link(values)
        elif tag == "img":
            self._image(values)
        elif tag in ("audio", "source"):
            self._audio(values)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag not in VOID_TAGS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        if tag in RAW_TAGS and self.skip:
            self.skip -= 1
        if tag == "a" and self.link is not None:
            self._close_link()
        if tag == "figure":
            self.caption_for = None
        self._pop(tag)

    def _push(self, tag: str, values: dict[str, str]) -> None:
        if tag in RAW_TAGS:
            self.skip += 1
        if tag in CHROME_TAGS or values.get("role") in ("navigation", "banner"):
            self.chrome += 1
            self.stack.append(f"chrome:{tag}")
        elif tag in ARTICLE_TAGS:
            self.article += 1
            self.stack.append(f"article:{tag}")
        elif tag not in VOID_TAGS:
            self.stack.append(tag)

    def _pop(self, tag: str) -> None:
        """Close the innermost open `tag` and everything left open inside it."""
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index].split(":")[-1] == tag:
                break
        else:
            return
        for closed in self.stack[index:]:
            if closed.startswith("chrome:"):
                self.chrome -= 1
            elif closed.startswith("article:"):
                self.article -= 1
        del self.stack[index:]

    def handle_data(self, data: str) -> None:
        if self.skip:
            return
        if self.link is not None:
            self.link.text.append(data)
        if "figcaption" in self.stack and self.caption_for is not None:
            self.caption_for.context = _clean(
                f"{self.caption_for.context} {data}", CONTEXT_CHARS
            )
        self.recent = (self.recent + " " + data)[-CONTEXT_CHARS * 2 :]

    # - - - Candidates - - -

    def _open_link(self, values: dict[str, str]) -> None:
        url = _absolute(self.base, values.get("href", ""))
        if url is None:
            return
        extension = _extension(url)
        kind: MaterialKind | None = None
        if extension in DOCUMENT_EXTENSIONS:
            kind = "document"
        elif extension in AUDIO_EXTENSIONS:
            kind = "audio"
        if kind is None or _JUNK.search(url):
            return
        self.link = _OpenLink(url, kind, _clean(self.recent, CONTEXT_CHARS), [])

    def finish(self) -> None:
        """Keep a link the markup never closed."""
        self._close_link()

    def _close_link(self) -> None:
        link = self.link
        self.link = None
        if link is None:
            return
        text = _clean(" ".join(link.text), TITLE_CHARS)
        self._add(link.url, link.kind, text, link.before)

    def _image(self, values: dict[str, str]) -> None:
        raw = values.get("src") or values.get("data-src") or ""
        url = _absolute(self.base, raw)
        if url is None or _extension(url) not in IMAGE_EXTENSIONS:
            return
        marks = " ".join(
            values.get(name, "") for name in ("class", "id", "alt", "role")
        )
        if _JUNK.search(url) or _JUNK.search(marks):
            return
        if values.get("aria-hidden") == "true" or values.get("role") == "presentation":
            return
        sizes = [_px(values.get("width")), _px(values.get("height"))]
        if any(size is not None and size < self.min_image_px for size in sizes):
            return
        alt = _clean(values.get("alt", ""), TITLE_CHARS)
        found = self._add(url, "image", alt, _clean(self.recent, CONTEXT_CHARS))
        if found is not None and "figure" in self.stack:
            self.caption_for = found

    def _audio(self, values: dict[str, str]) -> None:
        url = _absolute(self.base, values.get("src", ""))
        if url is None or _extension(url) not in AUDIO_EXTENSIONS:
            return
        if "audio" in self.stack or values.get("type", "").startswith("audio/"):
            self._add(url, "audio", "", _clean(self.recent, CONTEXT_CHARS))

    def _add(
        self, url: str, kind: MaterialKind, title: str, context: str
    ) -> _Found | None:
        if any(item.url == url for item in self.found):
            return None
        name = unquote(basename(urlsplit(url).path))
        found = _Found(url, kind, title or name, context, self.article > 0)
        self.found.append(found)
        return found


def extract_candidates(
    markup: str, page_url: str, *, limit: int, min_image_px: int = 200
) -> list[MaterialCandidate]:
    """The files of a page worth a look, at most `limit`, documents first."""
    if limit <= 0:
        return []
    page_host = urlsplit(page_url).hostname or ""
    scanner = _Scanner(page_url, min_image_px)
    try:
        scanner.feed(markup)
        scanner.close()
    except (AssertionError, ValueError):  # broken markup keeps what was found
        pass
    scanner.finish()
    found = scanner.found
    if any(item.kind == "image" and item.in_article for item in found):
        found = [i for i in found if i.kind != "image" or i.in_article]
    kept = [
        item
        for item in found
        if item.url != page_url
        and reputable(urlsplit(item.url).hostname or "", page_host)
    ]
    order = {"document": 0, "audio": 1, "image": 2}
    kept.sort(key=lambda item: order[item.kind])
    return [
        MaterialCandidate(item.url, item.kind, item.title, item.context)
        for item in kept[:limit]
    ]
