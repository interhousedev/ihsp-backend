"""LIB-1: `ItemCard` and `ItemDetail` JSON follow the TypeScript contract."""

from uuid import UUID

from app.interfaces.http.v1.library.catalogue.schemas_items import (
    ItemCardSchema,
    ItemDetailSchema,
    TocEntrySchema,
)
from app.modules.library.application.detail import (
    CanView,
    ItemDetailView,
    ItemFileView,
)
from app.modules.library.application.views import (
    BookCardView,
    ExternalCardView,
    ItemCardView,
    TagSource,
)
from app.modules.library.domain.enums import (
    ExternalAccess,
    FileFormat,
    ItemKind,
    ItemStatus,
    ItemType,
    Rights,
    TextStatus,
    Visibility,
)
from app.shared.ids import new_id

OFFICIAL_BOOK = BookCardView(Rights.OFFICIAL, None, False)


def _card(
    *,
    id: UUID | None = None,  # noqa: A002
    slug: str | None = "fizika-10-1a2b3c4d",
    kind: ItemKind = ItemKind.BOOK,
    tag_source: TagSource = "book",
    tag_label: str = "Library book",
    book: BookCardView | None = OFFICIAL_BOOK,
    external: ExternalCardView | None = None,
    unstored: bool = False,
) -> ItemCardView:
    return ItemCardView(
        id=None if unstored else (id or new_id()),
        slug=slug,
        kind=kind,
        type=ItemType.TEXTBOOK,
        title="Fizika 10",
        author_label="A. Author",
        language="uz_latn",
        year_published=2022,
        cover_url=None,
        description_excerpt=None,
        subjects=(),
        years_of_study=(1,),
        has_text=True,
        page_count=120,
        shelf_state=None,
        progress_percent=None,
        tag_source=tag_source,
        tag_label=tag_label,
        book=book,
        external=external,
    )


def _detail(card: ItemCardView, **changes: object) -> ItemDetailView:
    fields: dict[str, object] = {
        "card": card,
        "status": ItemStatus.PUBLISHED,
        "status_reason": None,
        "status_note": None,
        "visibility": Visibility.LYCEUM,
        "subtitle": None,
        "description": None,
        "publisher": None,
        "isbn": None,
        "files": (),
        "topics": (),
        "lists": (),
        "can": CanView(True, False, True, True, False),
    }
    return ItemDetailView(**{**fields, **changes})  # type: ignore[arg-type]


def test_card_leaves_out_the_blocks_that_do_not_apply() -> None:
    """LIB-1: `material?` and `external?` are absent, not null."""
    body = ItemCardSchema.from_view(_card()).model_dump(mode="json")

    assert "book" in body
    assert "material" not in body and "external" not in body
    assert body["tag"] == {"source": "book", "label": "Library book"}
    assert body["snippet"] is None and body["snippet_page"] is None


def test_nullable_keys_stay_as_null() -> None:
    """LIB-1: `cover_url`, `shelf_state`, `progress_percent` are `null`, not absent."""
    body = ItemCardSchema.from_view(_card()).model_dump(mode="json")

    for key in ("cover_url", "shelf_state", "progress_percent", "description_excerpt"):
        assert key in body and body[key] is None


def test_unstored_external_record_has_null_id_and_slug() -> None:
    """LIB-12: a UniLibrary search result that is not pinned yet."""
    card = _card(
        unstored=True,
        slug=None,
        kind=ItemKind.EXTERNAL,
        tag_source="unilibrary",
        tag_label="UniLibrary",
        book=None,
        external=ExternalCardView(
            "355186",
            1,
            ExternalAccess.OPEN,
            "Textbook",
            "Physics",
            "https://u/1",
            False,
        ),
    )

    body = ItemCardSchema.from_view(card).model_dump(mode="json")

    assert body["id"] is None and body["slug"] is None
    assert (
        body["external"]["category"] == 1 and body["external"]["source"] == "unilibrary"
    )
    assert "book" not in body


def test_detail_carries_card_fields_and_its_own() -> None:
    """LIB-1: `ItemDetail extends ItemCard`: one flat object."""
    file_id = new_id()
    view = _detail(
        _card(),
        files=(
            ItemFileView(
                file_id,
                FileFormat.PDF,
                True,
                120,
                1000,
                True,
                TextStatus.READY,
                ({"title": "Kirish", "level": 1, "page": 3, "extra": "x"},),
            ),
        ),
    )

    body = ItemDetailSchema.from_view(view).model_dump(mode="json")

    assert body["title"] == "Fizika 10" and body["status"] == "published"
    assert body["files"][0]["id"] == str(file_id)
    assert body["files"][0]["toc"] == [{"title": "Kirish", "level": 1, "page": 3}]
    assert body["can"]["report"] is True
    for absent in ("rights_box", "external_keywords", "external_isbn"):
        assert absent not in body


def test_toc_entry_keeps_page_for_pdf_and_href_for_epub() -> None:
    """LIB-1: `TocEntry` has `page` or `href`, never both as null."""
    pdf = TocEntrySchema.from_dict({"title": "A", "level": 1, "page": 4})
    epub = TocEntrySchema.from_dict({"title": "B", "level": 2, "href": "ch2.xhtml#b"})

    assert pdf.model_dump(mode="json") == {"title": "A", "level": 1, "page": 4}
    assert epub.model_dump(mode="json") == {
        "title": "B",
        "level": 2,
        "href": "ch2.xhtml#b",
    }


def test_external_detail_has_keywords_and_isbn_only_when_known() -> None:
    """LIB-12: `external_keywords` and `external_isbn` come from the detail call."""
    view = _detail(_card(), external_keywords=("optics",), external_isbn="978-1")

    body = ItemDetailSchema.from_view(view).model_dump(mode="json")

    assert body["external_keywords"] == ["optics"]
    assert body["external_isbn"] == "978-1"
    assert isinstance(UUID(body["id"]), UUID)
