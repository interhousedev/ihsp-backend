"""LIB-10: who may turn a library item into a notebook source."""

from app.modules.library.domain.bridge_rules import source_denial
from app.modules.library.domain.entities import Item
from app.modules.library.domain.enums import ItemStatus, TextStatus, Visibility
from app.shared.actor import Actor
from tests.factories.library import make_book, make_external, make_material

import pytest


def test_a_published_lyceum_book_may_be_read_by_a_student(student: Actor) -> None:
    """LIB-10: the ordinary case has no denial."""
    assert source_denial(make_book(), student) is None


def test_a_published_material_may_be_read_by_a_student(student: Actor) -> None:
    """LIB-10: materials are sources too."""
    assert source_denial(make_material(), student) is None


def test_a_missing_item_is_not_found(student: Actor) -> None:
    """LIB-10: an unknown id and a hidden one look the same."""
    assert source_denial(None, student) == "not_found"


def test_a_lyceum_book_is_not_found_for_someone_without_a_role(visitor: Actor) -> None:
    """LIB-10, LIB-1: lyceum-only books are closed to visitors."""
    assert source_denial(make_book(visibility=Visibility.LYCEUM), visitor) == (
        "not_found"
    )


def test_a_public_book_still_needs_a_lyceum_account_for_a_notebook(
    visitor: Actor,
) -> None:
    """LIB-10: notebooks belong to signed-in users."""
    assert source_denial(make_book(visibility=Visibility.PUBLIC), visitor) == (
        "not_found"
    )


def test_a_hidden_item_is_not_found(student: Actor) -> None:
    """LIB-10: hidden items never show up for students."""
    assert source_denial(make_book(visibility=Visibility.HIDDEN), student) == (
        "not_found"
    )


@pytest.mark.parametrize(
    "status", [ItemStatus.HELD, ItemStatus.UNPUBLISHED, ItemStatus.GONE]
)
def test_an_item_that_was_withdrawn_is_unavailable_not_missing(
    student: Actor, status: ItemStatus
) -> None:
    """LIB-10: held, unpublished and taken down items turn sources `unavailable`."""
    assert source_denial(make_book(status=status), student) == "unavailable"


def test_a_withdrawn_item_stays_not_found_for_someone_who_never_saw_it(
    visitor: Actor,
) -> None:
    """LIB-10: no hint about held items to people without access."""
    assert source_denial(make_book(status=ItemStatus.HELD), visitor) == "not_found"


@pytest.mark.parametrize(
    "status",
    [
        ItemStatus.DRAFT,
        ItemStatus.PENDING_REVIEW,
        ItemStatus.CHANGES_REQUESTED,
        ItemStatus.REJECTED,
    ],
)
def test_other_peoples_unpublished_work_is_not_found(
    student: Actor, status: ItemStatus
) -> None:
    """LIB-10: drafts and queue items must not leak through a notebook."""
    assert source_denial(make_material(status=status), student) == "not_found"


def test_an_owner_cannot_use_their_own_unpublished_upload(student: Actor) -> None:
    """LIB-10: only published items become sources, even for the owner."""
    own = make_material(status=ItemStatus.PENDING_REVIEW, uploader_id=student.user_id)

    assert source_denial(own, student) == "unavailable"


def test_a_librarian_cannot_use_a_held_item(librarian: Actor) -> None:
    """LIB-10: staff see held items but they are not sources."""
    assert source_denial(make_book(status=ItemStatus.HELD), librarian) == "unavailable"


def test_a_unilibrary_record_is_not_supported(student: Actor) -> None:
    """LIB-10, LIB-2: link-only records never become sources."""
    assert source_denial(make_external(), student) == "not_supported"


def test_an_item_without_files_has_no_text(student: Actor) -> None:
    """LIB-10: a published item with nothing to read."""
    bare: Item = make_book(files=[])

    assert source_denial(bare, student) == "no_text"


def test_the_text_status_of_a_file_is_not_a_matter_for_the_item_rules(
    student: Actor,
) -> None:
    """LIB-10: scans are reported per file by the reader, not here."""
    scan = make_book(text_status=TextStatus.NO_TEXT)

    assert source_denial(scan, student) is None
