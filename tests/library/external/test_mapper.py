"""LIB-12: UniLibrary payloads (recorded shapes of doc § 1.2) become records."""

import json
from typing import Any

from app.modules.library.domain.enums import ExternalAccess, ItemLanguage, ItemType
from app.modules.library.infrastructure.unilibrary.errors import UpstreamError
from app.modules.library.infrastructure.unilibrary.mapper import (
    map_detail,
    map_list_page,
    map_taxonomy,
)
from tests.library.external.support import load

import pytest

DESCRIPTION_MAX = 600


def _first_item(payload: dict[str, Any]) -> dict[str, Any]:
    first: dict[str, Any] = payload["result"]["data"][0]
    return first


def test_list_page_maps_both_records_and_the_paging() -> None:
    """LIB-12: the Laravel envelope gives page, last page and total."""
    page = map_list_page(load("list_page"), description_max=DESCRIPTION_MAX)

    assert (page.page, page.last_page, page.total) == (1, 12, 23)
    assert [r.external_id for r in page.records] == ["355186", "896986"]
    assert page.stale is False


def test_list_record_carries_the_facts_of_the_card() -> None:
    """LIB-12: title, authors, year, publisher, names, language, access, URLs."""
    page = map_list_page(load("list_page"), description_max=DESCRIPTION_MAX)

    record = page.records[0]

    assert record.title == "Elektronika va sxemalar 1"
    assert record.authors == "SH.K.Ismailov"
    assert record.year == 2021
    assert record.publisher == "Toshkent"
    assert (record.type_id, record.type_name) == (9, "Darslik")
    assert (record.field_id, record.field_name) == (27, "Fizika")
    assert (record.language_id, record.language_name) == (2, "O'zbek")
    assert record.item_type is ItemType.TEXTBOOK
    assert record.language is ItemLanguage.UZ_LATN
    assert record.access is ExternalAccess.OPEN
    assert record.category == 1
    assert record.views == 53
    assert record.view_url == "https://unilibrary.uz/literature/355186"
    assert record.cover_url == (
        "https://api.unilibrary.uz/storage/PublisherResourceImage/"
        "355186/images/1691471316.png"
    )
    assert record.description == (
        "Elektron sxemalar asoslari: diod, tranzistor, kuchaytirgichlar."
    )


def test_lotin_record_is_uzbek_in_latin_script_and_partly_open() -> None:
    """LIB-12: language id 26 "Lotin" is `uz_latn`; modifier 2 is `partial`."""
    page = map_list_page(load("list_page"), description_max=DESCRIPTION_MAX)

    record = page.records[1]

    assert record.language_id == 26
    assert record.language is ItemLanguage.UZ_LATN
    assert record.access is ExternalAccess.PARTIAL
    assert record.item_type is ItemType.MANUAL
    assert record.cover_url is None
    assert record.view_url == "https://unilibrary.uz/literature/896986"


def test_list_items_have_no_detail_only_fields() -> None:
    """LIB-12: `isbn`, `resource_page_count` and `keywords` come with the detail."""
    page = map_list_page(load("list_page"), description_max=DESCRIPTION_MAX)

    record = page.records[0]

    assert record.keywords is None
    assert record.isbn is None
    assert record.page_count is None


def test_detail_adds_keywords_isbn_and_pages() -> None:
    """LIB-12: the detail has the fields lists lack."""
    record = map_detail(load("detail"), category=1, description_max=DESCRIPTION_MAX)

    assert record is not None
    assert record.keywords == ("elektronika", "sxema", "tranzistor")
    assert record.isbn == "978-9943-00-111-1"
    assert record.page_count == 288
    assert record.access is ExternalAccess.OPEN


def test_missing_record_is_an_empty_result() -> None:
    """LIB-12: a missing id answers `200 {"result": []}`."""
    assert (
        map_detail(load("detail_empty"), category=1, description_max=DESCRIPTION_MAX)
        is None
    )


def test_file_urls_are_never_part_of_a_record() -> None:
    """LIB-12 / D3: only the cover link is kept; no file, media or storage path."""
    page = map_list_page(load("list_page"), description_max=DESCRIPTION_MAX)
    detail = map_detail(load("detail"), category=1, description_max=DESCRIPTION_MAX)
    assert detail is not None

    dumped = repr([*page.records, detail])

    assert "PublisherResourceFile" not in dumped
    assert "pdf" not in dumped
    assert "media" not in dumped


def test_description_is_cut_at_the_configured_limit() -> None:
    """LIB-12: `abstract_name` is cut with an ellipsis."""
    payload = load("list_page")
    _first_item(payload)["abstract_name"] = "so'z " * 300

    page = map_list_page(payload, description_max=100)

    description = page.records[0].description
    assert description is not None
    assert len(description) == 100
    assert description.endswith("…")


def test_category_comes_from_the_record_and_picks_the_url() -> None:
    """LIB-12: a dissertation links to `/dissertation/{id}`."""
    payload = load("list_page")
    _first_item(payload)["resource_category_id"] = 3

    page = map_list_page(payload, description_max=DESCRIPTION_MAX)

    assert page.records[0].category == 3
    assert page.records[0].view_url == "https://unilibrary.uz/dissertation/355186"


def test_record_without_a_known_category_is_dropped_from_a_page() -> None:
    """LIB-12: no guessed link; the other records of the page stay."""
    payload = load("list_page")
    _first_item(payload)["resource_category_id"] = 99

    page = map_list_page(payload, description_max=DESCRIPTION_MAX)

    assert [r.external_id for r in page.records] == ["896986"]


def test_record_without_an_id_or_title_is_dropped() -> None:
    """LIB-12: a malformed row does not break the page."""
    payload = load("list_page")
    payload["result"]["data"].append({"name": "No id"})
    payload["result"]["data"].append({"id": 5, "name": "  "})

    page = map_list_page(payload, description_max=DESCRIPTION_MAX)

    assert len(page.records) == 2


def test_cover_must_be_an_https_link() -> None:
    """LIB-12: we hotlink the cover, so only a web URL is accepted."""
    payload = load("list_page")
    _first_item(payload)["publisher_resource_icon"] = "javascript:alert(1)"

    page = map_list_page(payload, description_max=DESCRIPTION_MAX)

    assert page.records[0].cover_url is None


@pytest.mark.parametrize(
    "keywords",
    ["a, b; c", ["a", "b", "c"], [{"name": "a"}, {"name": "b"}, {"name": "c"}]],
)
def test_keywords_may_be_text_or_a_list(keywords: object) -> None:
    """LIB-12: the detail's keyword format is not fixed; all three are read."""
    payload = load("detail")
    payload["result"][0]["keywords"] = keywords

    record = map_detail(payload, category=1, description_max=DESCRIPTION_MAX)

    assert record is not None and record.keywords == ("a", "b", "c")


def test_detail_may_be_a_single_object() -> None:
    """LIB-12: tolerate `result` as an object instead of a one-element list."""
    payload = {"result": load("detail")["result"][0]}

    record = map_detail(payload, category=1, description_max=DESCRIPTION_MAX)

    assert record is not None and record.external_id == "355186"


@pytest.mark.parametrize("payload", ["text", [], {"result": "x"}, {"data": {}}])
def test_page_without_the_laravel_envelope_is_an_upstream_error(
    payload: object,
) -> None:
    """LIB-12: an unexpected body is a failure of the source, not an empty page."""
    with pytest.raises(UpstreamError) as caught:
        map_list_page(payload, description_max=DESCRIPTION_MAX)

    assert caught.value.kind == "bad_payload"


def test_detail_with_an_unexpected_body_is_an_upstream_error() -> None:
    """LIB-12: same for the detail."""
    with pytest.raises(UpstreamError):
        map_detail("oops", category=1, description_max=DESCRIPTION_MAX)


def test_page_numbers_default_when_the_server_leaves_them_out() -> None:
    """LIB-12: a page without paging keys is one page of what it holds."""
    payload = {
        "result": {"data": json.loads(json.dumps(load("list_page")))["result"]["data"]}
    }

    page = map_list_page(payload, description_max=DESCRIPTION_MAX)

    assert (page.page, page.last_page, page.total) == (1, 1, 2)


# - - - Taxonomies (row shape not verified: tolerant reading) - - -


def test_taxonomy_rows_per_language_give_one_entry_per_id() -> None:
    """LIB-12: rows repeat per language; the wanted one is chosen."""
    entries = map_taxonomy(load("taxonomy_fields"), "ru")

    assert [(e.id, e.name) for e in entries] == [
        (27, "Физика"),
        (25, "Математика"),
        (18, "Литература"),
    ]


def test_taxonomy_falls_back_to_another_language() -> None:
    """LIB-12: a missing translation falls back to uz, ru, en."""
    payload = {"result": [{"id": 1, "language": "en", "name": "Physics"}]}

    entries = map_taxonomy(payload, "uz")

    assert [(e.id, e.name) for e in entries] == [(1, "Physics")]


def test_types_of_other_categories_are_left_out() -> None:
    """LIB-12: the search is about literature (category 1)."""
    entries = map_taxonomy(load("taxonomy_types"), "en", category=1)

    assert [e.id for e in entries] == [9, 2, 19]


@pytest.mark.parametrize(
    "row",
    [
        {"id": 5, "name_uz": "Fizika", "name_ru": "Физика", "name_en": "Physics"},
        {"id": 5, "name": {"uz": "Fizika", "ru": "Физика", "en": "Physics"}},
        {
            "id": 5,
            "translations": [
                {"language": "uz", "name": "Fizika"},
                {"language": "ru", "name": "Физика"},
            ],
        },
    ],
)
def test_taxonomy_reads_other_plausible_shapes(row: dict[str, Any]) -> None:
    """LIB-12: the row shape is not verified; other usual layouts work."""
    entries = map_taxonomy({"result": [row]}, "ru")

    assert [(e.id, e.name) for e in entries] == [(5, "Физика")]


def test_taxonomy_may_be_paginated_and_skips_broken_rows() -> None:
    """LIB-12: `result.data` is read too; rows without id or name are skipped."""
    payload = {
        "result": {
            "data": [
                {"id": 1, "language": "uz", "name": "Fizika"},
                {"id": "x", "name": "Bad id"},
                {"id": 2},
            ]
        }
    }

    entries = map_taxonomy(payload, "uz")

    assert [(e.id, e.name) for e in entries] == [(1, "Fizika")]


def test_taxonomy_with_an_unexpected_body_is_an_upstream_error() -> None:
    """LIB-12: a body that holds no rows is a failure of the source."""
    with pytest.raises(UpstreamError):
        map_taxonomy({"result": "no"}, "uz")
