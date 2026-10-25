"""Jinja2 renderer of the public HTML pages (no JavaScript, noindex)."""

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from app.shared.i18n.core import I18nCore

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

TEMPLATES_DIR = Path(__file__).with_name("templates")


class JinjaPageRenderer:
    """Renders `templates/<name>.html` with a `t()` translation function."""

    def __init__(self, i18n: I18nCore, templates_dir: Path = TEMPLATES_DIR) -> None:
        """Create the Jinja environment with autoescaping and strict variables."""
        self.i18n = i18n
        self.env = Environment(
            loader=FileSystemLoader(str(templates_dir)),
            autoescape=select_autoescape(["html"]),
            undefined=StrictUndefined,
            trim_blocks=True,
            lstrip_blocks=True,
        )

    def render(self, template: str, locale: str, context: Mapping[str, Any]) -> str:
        """Return the HTML of `template` in the locale."""

        def translate(key: str, **params: str | int) -> str:
            return self.i18n.t(locale, key, **params)

        page = self.env.get_template(f"{template}.html")
        return page.render(t=translate, locale=locale, **context)
