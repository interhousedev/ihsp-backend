"""The Latin-normalised text that title, authors and description are searched in."""

from app.modules.library.domain.entities import Item
from app.modules.library.domain.enums import ItemLanguage
from app.shared.text import search_normalize

_UZBEK = {ItemLanguage.UZ_LATN, ItemLanguage.UZ_CYRL}


def build_search_text(item: Item) -> str:
    """Title, subtitle, authors and description, in the form a query is compared in.

    Uzbek items are transliterated to Latin so both scripts find each other; Russian
    and English items are only lower-cased. A material has no author list, so the
    uploader label stands in for it.
    """
    authors = item.authors or ([item.author_label] if item.author_label else [])
    parts = [item.title, item.subtitle or "", *authors, item.description or ""]
    language = "uz" if item.language in _UZBEK else item.language.value
    return search_normalize(" ".join(part for part in parts if part), language)
