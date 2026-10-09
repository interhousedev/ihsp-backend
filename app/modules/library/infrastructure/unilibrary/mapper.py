"""UniLibrary payloads (doc § 1.2) to `ExternalRecord`, pages and taxonomies.

Reading is tolerant: a record that cannot be linked is dropped from its page, and
the taxonomy row shape (not verified in the probe) may come in several layouts.
A body that is not the expected envelope at all is an `UpstreamError`.
"""

from collections.abc import Mapping
from typing import TypeGuard

from app.modules.library.domain.external_mapping import (
    CATEGORY_PATHS,
    access_for,
    cut_description,
    item_type_for,
    language_for,
    view_url,
)
from app.modules.library.infrastructure.unilibrary.errors import UpstreamError
from app.modules.library.ports.external_catalog import (
    ExternalPage,
    ExternalRecord,
    TaxonomyEntry,
)

import structlog

log = structlog.get_logger(__name__)

LANGUAGE_ORDER = ("uz", "ru", "en")
YEAR_RANGE = range(1000, 2201)
UNTAGGED = ""


def _is_mapping(value: object) -> TypeGuard[Mapping[str, object]]:
    return isinstance(value, Mapping)


def _int(value: object) -> int | None:
    """An integer from a JSON number or a numeric string; booleans are not numbers."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().lstrip("-").isdecimal():
        return int(value.strip())
    return None


def _str(value: object) -> str | None:
    """Trimmed text, or None when empty or not text."""
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return None


def _web_url(value: object) -> str | None:
    """The cover link: only http(s) URLs are hotlinked."""
    text = _str(value)
    if text and text.lower().startswith(("https://", "http://")):
        return text
    return None


def _keyword_text(item: object) -> str:
    """One keyword: a text or an object with a `name`."""
    if _is_mapping(item):
        return _str(item.get("name")) or ""
    return _str(item) or ""


def _keywords(value: object) -> tuple[str, ...]:
    """Keywords from a text, a list of texts or a list of `{name}` objects."""
    if isinstance(value, str):
        parts = value.replace(";", ",").split(",")
    elif isinstance(value, list):
        parts = [_keyword_text(item) for item in value]
    else:
        return ()
    return tuple(part.strip() for part in parts if part.strip())


def _record(
    raw: Mapping[str, object],
    *,
    category_hint: int | None,
    description_max: int,
    detail: bool,
) -> ExternalRecord | None:
    """One record, or None when it has no id, no title or no linkable category."""
    ident = _int(raw.get("id"))
    title = _str(raw.get("name"))
    category = _int(raw.get("resource_category_id")) or category_hint
    if ident is None or title is None or category not in CATEGORY_PATHS:
        log.warning("unilibrary_record_skipped", id=raw.get("id"), category=category)
        return None
    external_id = str(ident)
    type_id = _int(raw.get("resource_type_id"))
    language_id = _int(raw.get("resource_language_id"))
    year = _int(raw.get("publisher_year"))
    keywords = _keywords(raw.get("keywords")) if detail else None
    pages = _int(raw.get("resource_page_count")) if detail else None
    return ExternalRecord(
        external_id=external_id,
        category=category,
        title=title,
        authors=_str(raw.get("authors")) or "",
        access=access_for(_int(raw.get("resource_modifier_id"))),
        view_url=view_url(category, external_id),
        item_type=item_type_for(category, type_id),
        language=language_for(language_id),
        year=year if year in YEAR_RANGE else None,
        publisher=_str(raw.get("publisher_name")),
        type_id=type_id,
        type_name=_str(raw.get("resource_type_name")),
        field_id=_int(raw.get("resource_field_id")),
        field_name=_str(raw.get("resource_field_name")),
        language_id=language_id,
        language_name=_str(raw.get("resource_language_name")),
        description=cut_description(_str(raw.get("abstract_name")), description_max),
        cover_url=_web_url(raw.get("publisher_resource_icon")),
        views=max(_int(raw.get("count_view")) or 0, 0),
        keywords=keywords,
        isbn=_str(raw.get("isbn")) if detail else None,
        page_count=pages if pages and pages > 0 else None,
    )


# - - - Lists and details - - -


def map_list_page(
    payload: object, *, description_max: int, category: int | None = None
) -> ExternalPage:
    """A Laravel page (`result.data`) of list items; `category` is the search's."""
    result = payload.get("result") if _is_mapping(payload) else None
    data = result.get("data") if _is_mapping(result) else None
    if not _is_mapping(result) or not isinstance(data, list):
        raise UpstreamError("bad_payload", detail="list without result.data")
    records = tuple(
        record
        for raw in data
        if _is_mapping(raw)
        for record in [
            _record(
                raw,
                category_hint=category,
                description_max=description_max,
                detail=False,
            )
        ]
        if record is not None
    )
    page = _int(result.get("current_page")) or 1
    return ExternalPage(
        records=records,
        page=page,
        last_page=max(_int(result.get("last_page")) or 1, page),
        total=_int(result.get("total")) or len(records),
    )


def map_detail(
    payload: object, *, category: int, description_max: int
) -> ExternalRecord | None:
    """The record of a detail answer; `{"result": []}` means it does not exist."""
    if not _is_mapping(payload) or "result" not in payload:
        raise UpstreamError("bad_payload", detail="detail without result")
    result = payload["result"]
    raw = (result[0] if result else None) if isinstance(result, list) else result
    if raw is None:
        return None
    if not _is_mapping(raw):
        raise UpstreamError("bad_payload", detail="detail is not an object")
    return _record(
        raw, category_hint=category, description_max=description_max, detail=True
    )


# - - - Taxonomies - - -


def _taxonomy_rows(payload: object) -> list[object]:
    result = payload.get("result") if _is_mapping(payload) else None
    if isinstance(result, list):
        return result
    data = result.get("data") if _is_mapping(result) else None
    if isinstance(data, list):
        return data
    raise UpstreamError("bad_payload", detail="taxonomy without rows")


def _named(value: object) -> str | None:
    """A name that is a non-empty text."""
    return _str(value)


def _row_names(row: Mapping[str, object]) -> dict[str, str]:
    """Every name of a row by language (`""` when the row does not say)."""
    names: dict[str, str] = {}
    name = row.get("name")
    if _is_mapping(name):
        names.update(
            {lang: str(text).strip() for lang, text in name.items() if _named(text)}
        )
    elif _named(name):
        language = _str(row.get("language") or row.get("lang") or row.get("locale"))
        names[language or UNTAGGED] = str(name).strip()
    for language in LANGUAGE_ORDER:
        if _named(row.get(f"name_{language}")):
            names[language] = str(row[f"name_{language}"]).strip()
    names.update(_translated_names(row.get("translations")))
    return names


def _translated_names(translations: object) -> dict[str, str]:
    """Names from a `translations: [{language, name}]` list."""
    if not isinstance(translations, list):
        return {}
    names: dict[str, str] = {}
    for item in translations:
        if _is_mapping(item) and _named(item.get("name")):
            language = _str(item.get("language") or item.get("lang")) or UNTAGGED
            names[language] = str(item["name"]).strip()
    return names


def _pick(names: Mapping[str, str], language: str) -> str | None:
    for candidate in (language, *LANGUAGE_ORDER, UNTAGGED):
        if names.get(candidate):
            return names[candidate]
    return next(iter(names.values()), None)


def map_taxonomy(
    payload: object, language: str, *, category: int | None = None
) -> tuple[TaxonomyEntry, ...]:
    """Types, fields or languages in one language (ids are stable across languages).

    With `category`, rows that name another `resource_category_id` are left out.
    """
    by_id: dict[int, dict[str, str]] = {}
    for row in _taxonomy_rows(payload):
        if not _is_mapping(row):
            continue
        ident = _int(row.get("id"))
        row_category = _int(row.get("resource_category_id"))
        if ident is None or (category and row_category and row_category != category):
            continue
        by_id.setdefault(ident, {}).update(_row_names(row))
    entries = (
        TaxonomyEntry(id=ident, name=name)
        for ident, names in by_id.items()
        for name in [_pick(names, language)]
        if name
    )
    return tuple(entries)
