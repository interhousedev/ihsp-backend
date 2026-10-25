"""schema.org JSON-LD of an item page (`Book` for books, `CreativeWork` otherwise)."""

import json

from app.modules.library.application.catalogue.public_pages import PublicItemPage
from app.modules.library.domain.enums import ItemKind


def json_ld(page: PublicItemPage) -> str:
    """JSON safe to put inside `<script type="application/ld+json">`."""
    data: dict[str, object] = {
        "@context": "https://schema.org",
        "@type": "Book" if page.kind is ItemKind.BOOK else "CreativeWork",
        "name": page.title,
        "url": page.canonical_url,
        "inLanguage": _language_tag(page.language.value),
        "isAccessibleForFree": page.indexable,
    }
    if page.authors:
        data["author"] = [{"@type": "Person", "name": name} for name in page.authors]
    optional = {
        "description": page.description,
        "image": page.cover_url,
        "publisher": page.publisher,
        "isbn": page.isbn,
        "datePublished": str(page.year_published) if page.year_published else None,
    }
    data.update({key: value for key, value in optional.items() if value})
    # `<` is escaped so that no text can close the script element.
    return json.dumps(data, ensure_ascii=False).replace("<", "\\u003c")


def _language_tag(language: str) -> str:
    return {
        "uz_latn": "uz-Latn",
        "uz_cyrl": "uz-Cyrl",
        "ru": "ru",
        "en": "en",
        "qq": "kaa",
    }.get(language, "und")
