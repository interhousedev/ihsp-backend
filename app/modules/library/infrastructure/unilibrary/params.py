"""Our search as the query of the UniLibrary list endpoint, and its cache key."""

import hashlib
import json
import re

from app.modules.library.domain.external_mapping import modifier_id_for
from app.modules.library.ports.external_catalog import ExternalSearch

NAME_LANGUAGES = ("uz", "ru", "en")
MAX_LIMIT = 100  # UniLibrary accepted 100 per page in the probe (doc 1.2)
_SPACES = re.compile(r"\s+")

Query = dict[str, str | int]


def list_query(search: ExternalSearch) -> Query:
    """Query parameters of `guest-publisher-resources-with-media`.

    Only set filters are sent. Newest first (`sort=desc`, ordered by id), so a browse
    shows new records at the top.
    """
    query: Query = {
        "page": max(search.page, 1),
        "limit": min(max(search.limit, 1), MAX_LIMIT),
        "language": search.language if search.language in NAME_LANGUAGES else "uz",
        "sort": "desc",
        "sort_direction": "id",
        "resource_category_id": search.category,
    }
    text = _SPACES.sub(" ", search.q or "").strip()
    if text:
        query["name"] = text
    if search.field_id is not None:
        query["resource_field_id"] = search.field_id
    if search.type_id is not None:
        query["resource_type_id"] = search.type_id
    if search.language_id is not None:
        query["resource_language_id"] = search.language_id
    if search.access is not None:
        query["resource_modifier_id"] = modifier_id_for(search.access)
    return query


def list_cache_key(query: Query) -> str:
    """`library:ext:list:{sha1(params)}` over the normalised parameters."""
    canonical = json.dumps(query, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha1(canonical.encode(), usedforsecurity=False).hexdigest()
    return f"library:ext:list:{digest}"
