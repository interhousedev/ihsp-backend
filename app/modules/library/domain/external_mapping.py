"""How UniLibrary ids and texts turn into lyceum values (doc §§ 1.2, 3.2, 3.3).

Pure rules, no I/O. The HTTP client and the mapper in `infrastructure/unilibrary`
apply them to the payloads.
"""

import html
import re

from app.modules.library.domain.enums import ExternalAccess, ItemLanguage, ItemType

UNILIBRARY_SITE = "https://unilibrary.uz"
"""Public pages of the records (not the API host)."""

CATEGORY_PATHS: dict[int, str] = {
    1: "literature",
    2: "monograph",
    3: "dissertation",
    4: "articles",
}
LITERATURE = 1
ARTICLE = 4

_ACCESS: dict[int, ExternalAccess] = {
    1: ExternalAccess.OPEN,
    2: ExternalAccess.PARTIAL,
    3: ExternalAccess.CLOSED,
}
_MODIFIER_IDS: dict[ExternalAccess, int] = {a: i for i, a in _ACCESS.items()}
# Language `26` "Lotin" is how UniLibrary files Uzbek in Latin script.
_LANGUAGES: dict[int, ItemLanguage] = {
    2: ItemLanguage.UZ_LATN,
    26: ItemLanguage.UZ_LATN,
    3: ItemLanguage.RU,
    7: ItemLanguage.EN,
    6: ItemLanguage.QQ,
}
# Our code -> the UniLibrary id the search filter sends (`uz_cyrl` has none).
_LANGUAGE_IDS: dict[str, int] = {
    ItemLanguage.UZ_LATN.value: 2,
    ItemLanguage.RU.value: 3,
    ItemLanguage.EN.value: 7,
    ItemLanguage.QQ.value: 6,
}
# Types of category 1 (doc 1.2) onto the lyceum list (doc 3.2); the rest is `other`.
_LITERATURE_TYPES: dict[int, ItemType] = {
    9: ItemType.TEXTBOOK,
    2: ItemType.MANUAL,
    3: ItemType.MANUAL,
    11: ItemType.MANUAL,
    19: ItemType.FICTION,
    20: ItemType.DICTIONARY,
    21: ItemType.REFERENCE,
}
_TAG = re.compile(r"<[^>]+>")
_SPACES = re.compile(r"\s+")
ELLIPSIS = "…"


def view_url(category: int, external_id: str) -> str:
    """The public page of a record: `https://unilibrary.uz/literature/896986`."""
    path = CATEGORY_PATHS.get(category)
    if path is None:
        raise ValueError(f"unknown UniLibrary category {category}")
    return f"{UNILIBRARY_SITE}/{path}/{external_id}"


def access_for(modifier_id: int | None) -> ExternalAccess:
    """`resource_modifier_id` 1, 2, 3 to open, partial, closed (unknown: closed)."""
    if modifier_id is None:
        return ExternalAccess.CLOSED
    return _ACCESS.get(modifier_id, ExternalAccess.CLOSED)


def modifier_id_for(access: ExternalAccess) -> int:
    """The `resource_modifier_id` that selects an access class in a search."""
    return _MODIFIER_IDS[access]


def language_for(language_id: int | None) -> ItemLanguage:
    """`resource_language_id` to our language and script (unknown: other)."""
    if language_id is None:
        return ItemLanguage.OTHER
    return _LANGUAGES.get(language_id, ItemLanguage.OTHER)


def item_type_for(category: int, type_id: int | None) -> ItemType:
    """The lyceum type of a record; type ids are known for literature only."""
    if category == ARTICLE:
        return ItemType.ARTICLE
    if category != LITERATURE or type_id is None:
        return ItemType.OTHER
    return _LITERATURE_TYPES.get(type_id, ItemType.OTHER)


def language_id_for_code(value: str) -> int | None:
    """The `resource_language_id` for a search filter: a UniLibrary id or our code."""
    value = value.strip()
    if value.isdecimal():
        return int(value)
    return _LANGUAGE_IDS.get(value)


def cut_description(text: str | None, limit: int) -> str | None:
    """Plain text of `abstract_name`, cut to `limit` characters with an ellipsis."""
    if not text:
        return None
    plain = _SPACES.sub(" ", html.unescape(_TAG.sub(" ", text))).strip()
    if not plain:
        return None
    if len(plain) <= limit:
        return plain
    return plain[: limit - 1].rstrip() + ELLIPSIS
