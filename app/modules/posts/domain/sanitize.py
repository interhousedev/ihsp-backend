"""Keep only the HTML tags Telegram accepts (parse_mode HTML); escape the rest."""

from html import escape
from html.parser import HTMLParser
from typing import Final
from urllib.parse import urlsplit

SIMPLE: Final = frozenset(
    {"b", "strong", "i", "em", "u", "ins", "s", "strike", "del", "tg-spoiler", "code"}
)
DROP_CONTENT: Final = frozenset({"script", "style", "iframe", "object", "template"})
LINK_SCHEMES: Final = frozenset({"http", "https", "tg", "mailto"})


class _Sanitizer(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.open: list[str] = []
        self.skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in DROP_CONTENT:
            self.skip += 1
            return
        if self.skip:
            return
        values = {name: value or "" for name, value in attrs}
        if tag == "br":
            self.out.append("\n")
            return
        if tag in ("p", "div"):
            return
        opening = self._opening(tag, values)
        if opening is not None:
            self.out.append(opening)
            self.open.append(tag)

    def _opening(self, tag: str, values: dict[str, str]) -> str | None:
        if tag in SIMPLE:
            return f"<{tag}>"
        if tag == "span" and values.get("class") == "tg-spoiler":
            return '<span class="tg-spoiler">'
        if tag == "a":
            href = values.get("href", "").strip()
            if urlsplit(href).scheme.lower() not in LINK_SCHEMES:
                return None
            return f'<a href="{escape(href, quote=True)}">'
        if tag == "pre":
            return "<pre>"
        if tag == "blockquote":
            return (
                "<blockquote expandable>" if "expandable" in values else "<blockquote>"
            )
        return None

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "br" and not self.skip:
            self.out.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in DROP_CONTENT:
            self.skip = max(self.skip - 1, 0)
            return
        if self.skip:
            return
        if tag in ("p", "div"):
            self.out.append("\n")
            return
        if tag in self.open:
            while self.open:
                last = self.open.pop()
                self.out.append(f"</{last}>")
                if last == tag:
                    break

    def handle_data(self, data: str) -> None:
        if not self.skip:
            self.out.append(escape(data, quote=False))

    def result(self) -> str:
        while self.open:
            self.out.append(f"</{self.open.pop()}>")
        return "".join(self.out)


def sanitize_telegram_html(text: str) -> str:
    """Telegram-safe HTML: allowed tags kept (closed), others dropped, text escaped.

    Markdown characters are text and pass unchanged; the bot renders the result
    with the shared rich-text renderer.
    """
    parser = _Sanitizer()
    parser.feed(text)
    parser.close()
    return parser.result()
