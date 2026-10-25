"""Jinja2 rendering of the library's public HTML pages (no JavaScript)."""

from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path

from app.shared.i18n.core import I18nCore

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

TEMPLATES_DIR = Path(__file__).with_name("templates")


@lru_cache(maxsize=1)
def _environment() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=select_autoescape(["html"]),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )


def render(
    template: str, locale: str, i18n: I18nCore, context: Mapping[str, object]
) -> str:
    """The HTML of `templates/<template>.html` with a `t()` translation function."""

    def translate(key: str, **params: str | int) -> str:
        return i18n.t(locale, key, **params)

    page = _environment().get_template(f"{template}.html")
    return page.render(t=translate, locale=locale, **context)
