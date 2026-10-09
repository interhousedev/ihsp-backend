"""LIB-3: the form data of a book, the item built from it and its life cycle."""

from datetime import timedelta

from app.modules.library.domain.catalogue_books import (
    BookData,
    apply_book_data,
    book_data_from,
    check_book_data,
    new_book,
    publish_book,
    take_down_book,
    unpublish_book,
)
from app.modules.library.domain.entities import SubjectLink, TopicLink
from app.modules.library.domain.enums import (
    ItemKind,
    ItemLanguage,
    ItemStatus,
    ItemType,
    Rights,
    SubjectRole,
    Visibility,
)
from app.modules.library.domain.errors import (
    NotEditableError,
    VisibilityConflictError,
)
from app.shared.ids import new_id
from tests.factories.library import NOW

import pytest
from pydantic import ValidationError

OWNER = new_id()


def _data(**changes: object) -> BookData:
    base = BookData(
        title="O'tkan kunlar",
        authors=["Abdulla Qodiriy", "  "],
        language=ItemLanguage.UZ_LATN,
        type=ItemType.FICTION,
        rights=Rights.PUBLIC_DOMAIN,
        rights_basis={"author_death_year": 1938, "rule": "life+70", "x": ""},
        years_of_study=[2, 1, 2],
        visibility=Visibility.PUBLIC,
    )
    return base.model_copy(update=changes)


def test_new_book_is_a_draft_owned_by_the_librarian() -> None:
    """LIB-3: created as a draft, slug from the title, search text ready."""
    item_id = new_id()

    item = new_book(_data(), item_id=item_id, owner_id=OWNER, now=NOW)

    assert item.kind is ItemKind.BOOK
    assert item.status is ItemStatus.DRAFT
    assert item.owner_id == OWNER and item.created_by == OWNER
    assert item.slug.startswith("o-tkan-kunlar-")
    assert item.author_label == "Abdulla Qodiriy"
    assert item.authors == ["Abdulla Qodiriy"]
    assert item.years_of_study == [1, 2]
    assert item.search_text.startswith("oʻtkan kunlar")


def test_empty_values_are_dropped_from_the_rights_basis() -> None:
    """LIB-3: only recorded facts are stored."""
    item = new_book(_data(), item_id=new_id(), owner_id=OWNER, now=NOW)

    assert item.book is not None
    assert item.book.rights_basis == {"author_death_year": 1938, "rule": "life+70"}


def test_editing_the_title_rebuilds_the_search_text_but_keeps_the_slug() -> None:
    """LIB-7: `search_text` follows title, authors and description changes."""
    item = new_book(_data(), item_id=new_id(), owner_id=OWNER, now=NOW)
    slug = item.slug

    apply_book_data(
        item,
        _data(title="Mehrobdan chayon", description="Roman"),
        now=NOW + timedelta(hours=1),
    )

    assert item.slug == slug
    assert "mehrobdan chayon" in item.search_text and "roman" in item.search_text
    assert "tkan" not in item.search_text
    assert item.updated_at == NOW + timedelta(hours=1)


def test_editing_keeps_who_checked_the_rights() -> None:
    """LIB-3: the recorded check survives an edit of other fields."""
    item = new_book(_data(), item_id=new_id(), owner_id=OWNER, now=NOW)
    publish_book(item, actor_id=OWNER, now=NOW)

    apply_book_data(item, _data(publisher="Sharq"), now=NOW)

    assert item.book is not None and item.book.rights_checked_by == OWNER


def test_round_trip_back_to_form_data() -> None:
    """LIB-3: the editor gets the same data it saved."""
    data = _data(
        subjects=[SubjectLink(new_id(), SubjectRole.TEXTBOOK, 1)],
        topics=[TopicLink(new_id(), 10, 20)],
        translators=["T. Translator"],
        isbn="978-9943-1",
    )
    item = new_book(data, item_id=new_id(), owner_id=OWNER, now=NOW)

    back = book_data_from(item, data.subjects, data.topics)

    assert back.title == data.title
    assert back.authors == ["Abdulla Qodiriy"]
    assert back.subjects == data.subjects and back.topics == data.topics
    assert back.translators == ["T. Translator"]
    assert back.rights_basis == {"author_death_year": 1938, "rule": "life+70"}


def test_public_visibility_with_permission_rights_is_refused() -> None:
    """LIB-3: the form data check rejects the combination."""
    with pytest.raises(VisibilityConflictError):
        check_book_data(_data(rights=Rights.PERMISSION, visibility=Visibility.PUBLIC))


def test_title_must_not_be_empty() -> None:
    """LIB-3: a book has a title."""
    with pytest.raises(ValidationError):
        BookData.model_validate({**_data().model_dump(), "title": ""})


def test_publish_records_who_checked_the_rights_and_when() -> None:
    """LIB-3: a published book has a rights check on record."""
    item = new_book(_data(), item_id=new_id(), owner_id=OWNER, now=NOW)
    librarian = new_id()

    publish_book(item, actor_id=librarian, now=NOW + timedelta(days=1))

    assert item.status is ItemStatus.PUBLISHED
    assert item.published_at == NOW + timedelta(days=1)
    assert item.reviewed_by == librarian
    assert item.book is not None
    assert item.book.rights_checked_by == librarian
    assert item.book.rights_checked_at == NOW + timedelta(days=1)


def test_publishing_a_published_book_is_not_editable() -> None:
    """LIB-3: only drafts and unpublished books can be published."""
    item = new_book(_data(), item_id=new_id(), owner_id=OWNER, now=NOW)
    publish_book(item, actor_id=OWNER, now=NOW)

    with pytest.raises(NotEditableError) as caught:
        publish_book(item, actor_id=OWNER, now=NOW)

    assert caught.value.code == "library/not-editable"


def test_unpublish_keeps_the_note_and_the_first_publication_date() -> None:
    """LIB-3: a republished book keeps its original `published_at`."""
    item = new_book(_data(), item_id=new_id(), owner_id=OWNER, now=NOW)
    publish_book(item, actor_id=OWNER, now=NOW)

    unpublish_book(item, actor_id=OWNER, now=NOW + timedelta(days=1), note="typo")
    assert item.status is ItemStatus.UNPUBLISHED
    assert item.status_reason == "unpublished" and item.status_note == "typo"

    publish_book(item, actor_id=OWNER, now=NOW + timedelta(days=2))
    assert item.published_at == NOW
    assert item.status_reason is None and item.status_note is None


def test_takedown_sets_the_reason_and_is_allowed_for_held_books() -> None:
    """LIB-3: a taken-down book keeps its reason."""
    item = new_book(_data(), item_id=new_id(), owner_id=OWNER, now=NOW)
    publish_book(item, actor_id=OWNER, now=NOW)
    item.status = ItemStatus.HELD

    take_down_book(item, actor_id=OWNER, now=NOW, note="copyright request")

    assert item.status is ItemStatus.UNPUBLISHED
    assert item.status_reason == "takedown"
    assert item.status_note == "copyright request"


def test_draft_cannot_be_unpublished() -> None:
    """LIB-3: nothing to withdraw."""
    item = new_book(_data(), item_id=new_id(), owner_id=OWNER, now=NOW)

    with pytest.raises(NotEditableError):
        unpublish_book(item, actor_id=OWNER, now=NOW, note=None)
