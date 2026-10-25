"""In-memory `ExternalCatalog`: scripted records, failures, call counters."""

import math
from collections.abc import Awaitable, Callable

from app.modules.library.domain.enums import (
    ExternalAccess,
    ItemLanguage,
    ItemType,
)
from app.modules.library.domain.errors import ExternalUnavailableError
from app.modules.library.domain.external_mapping import view_url
from app.modules.library.ports.external_catalog import (
    ExternalPage,
    ExternalRecord,
    ExternalSearch,
    ExternalTaxonomies,
    TaxonomyEntry,
)


def make_record(external_id: str = "355186", **fields: object) -> ExternalRecord:
    """A list-level record of literature; keyword fields replace the defaults."""
    values: dict[str, object] = {
        "external_id": external_id,
        "category": 1,
        "title": "Elektronika va sxemalar 1",
        "authors": "SH.K.Ismailov",
        "access": ExternalAccess.OPEN,
        "item_type": ItemType.TEXTBOOK,
        "language": ItemLanguage.UZ_LATN,
        "year": 2021,
        "publisher": "Toshkent",
        "type_id": 9,
        "type_name": "Darslik",
        "field_id": 27,
        "field_name": "Fizika",
        "language_id": 2,
        "language_name": "O'zbek",
        "description": "Elektron sxemalar asoslari.",
        "cover_url": f"https://api.unilibrary.uz/storage/{external_id}.png",
        "views": 5,
    }
    values.update(fields)
    category = values["category"]
    assert isinstance(category, int)
    values.setdefault("view_url", view_url(category, external_id))
    return ExternalRecord(**values)  # type: ignore[arg-type]


def make_detail(external_id: str = "355186", **fields: object) -> ExternalRecord:
    """The same record as the detail call returns it (keywords, ISBN, pages)."""
    defaults: dict[str, object] = {
        "keywords": ("elektronika", "sxema"),
        "isbn": "978-9943-00-111-1",
        "page_count": 288,
    }
    defaults.update(fields)
    return make_record(external_id, **defaults)


class FakeExternalCatalog:
    """Filters and pages the scripted records like the real source would."""

    def __init__(self) -> None:
        """Start empty: add records with `add`; set `down` to fail."""
        self.records: dict[str, ExternalRecord] = {}
        self.details: dict[str, ExternalRecord] = {}
        self.down: ExternalUnavailableError | None = None
        self.stale = False
        self.search_calls: list[ExternalSearch] = []
        self.get_calls: list[tuple[str, int, str]] = []
        self.taxonomy_calls: list[str] = []
        self.on_get: Callable[[str], Awaitable[None]] | None = None
        self.taxonomy_value = ExternalTaxonomies(
            types=(TaxonomyEntry(9, "Darslik"), TaxonomyEntry(2, "Qo'llanma")),
            fields=(TaxonomyEntry(27, "Fizika"), TaxonomyEntry(25, "Matematika")),
            languages=(TaxonomyEntry(2, "O'zbek"), TaxonomyEntry(26, "Lotin")),
        )

    def add(self, record: ExternalRecord, detail: ExternalRecord | None = None) -> None:
        """Make a record known; `detail` is what `get` returns (default: the record)."""
        self.records[record.external_id] = record
        self.details[record.external_id] = detail or record

    def unavailable(self, retry_after: int = 60) -> None:
        """Fail every call like an open breaker with nothing cached."""
        self.down = ExternalUnavailableError(params={"retry_after": retry_after})

    @property
    def calls(self) -> int:
        """Every call made so far."""
        return len(self.search_calls) + len(self.get_calls) + len(self.taxonomy_calls)

    def _matches(self, record: ExternalRecord, params: ExternalSearch) -> bool:
        needle = (params.q or "").casefold()
        text = f"{record.title} {record.authors}".casefold()
        checks = [
            record.category == params.category,
            needle in text,
            params.field_id in (None, record.field_id),
            params.type_id in (None, record.type_id),
            params.language_id in (None, record.language_id),
            params.access in (None, record.access),
        ]
        return all(checks)

    async def search(self, params: ExternalSearch) -> ExternalPage:
        """The matching records of the requested page."""
        self.search_calls.append(params)
        if self.down:
            raise self.down
        found = [r for r in self.records.values() if self._matches(r, params)]
        start = (params.page - 1) * params.limit
        return ExternalPage(
            records=tuple(found[start : start + params.limit]),
            page=params.page,
            last_page=max(math.ceil(len(found) / params.limit), 1),
            total=len(found),
            stale=self.stale,
        )

    async def get(
        self, external_id: str, *, category: int, language: str
    ) -> tuple[ExternalRecord | None, bool]:
        """The detail of a record or None."""
        self.get_calls.append((external_id, category, language))
        if self.on_get is not None:
            await self.on_get(external_id)
        if self.down:
            raise self.down
        return self.details.get(external_id), self.stale

    async def taxonomies(self, language: str) -> ExternalTaxonomies:
        """The scripted filter lists."""
        self.taxonomy_calls.append(language)
        if self.down:
            raise self.down
        return self.taxonomy_value
