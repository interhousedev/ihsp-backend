"""LIB-1, LIB-3, LIB-13: who may see, read and download an item."""

from collections.abc import Callable

from app.modules.library.domain.access import (
    can_add_to_notebook,
    can_download,
    can_read_content,
    can_view,
)
from app.modules.library.domain.enums import ItemStatus, Rights, Visibility
from app.shared.actor import Actor, Role
from tests.factories.library import make_book, make_external, make_material

import pytest


@pytest.fixture
def student(make_actor: Callable[..., Actor]) -> Actor:
    """A student."""
    return make_actor(Role.STUDENT)


@pytest.fixture
def librarian(make_actor: Callable[..., Actor]) -> Actor:
    """A librarian."""
    return make_actor(Role.LIBRARIAN)


def test_anonymous_sees_only_public_published_items() -> None:
    """LIB-1: public books are open to visitors, lyceum books are not."""
    public = make_book(visibility=Visibility.PUBLIC, rights=Rights.PUBLIC_DOMAIN)
    lyceum = make_book(visibility=Visibility.LYCEUM)

    assert can_view(public, None)
    assert not can_view(lyceum, None)


@pytest.mark.parametrize(
    "status",
    [
        ItemStatus.DRAFT,
        ItemStatus.PENDING_REVIEW,
        ItemStatus.CHANGES_REQUESTED,
        ItemStatus.HELD,
        ItemStatus.REJECTED,
        ItemStatus.UNPUBLISHED,
    ],
)
def test_students_never_see_unpublished_items_of_others(
    status: ItemStatus, student: Actor
) -> None:
    """LIB-13: held, rejected and unpublished items are a 404 for everyone else."""
    item = make_material(status=status)

    assert not can_view(item, student)


def test_owner_sees_their_item_in_every_status(student: Actor) -> None:
    """LIB-13: the uploader follows the status of their upload."""
    item = make_material(status=ItemStatus.REJECTED, uploader_id=student.user_id)

    assert can_view(item, student)


def test_librarian_sees_the_queue_but_not_foreign_drafts(librarian: Actor) -> None:
    """LIB-2: a librarian reviews pending items; drafts are private."""
    assert can_view(make_material(status=ItemStatus.PENDING_REVIEW), librarian)
    assert not can_view(make_material(status=ItemStatus.DRAFT), librarian)


def test_hidden_items_are_visible_to_staff_only(
    student: Actor, librarian: Actor
) -> None:
    """LIB-2: `hidden` removes an item from everyone but librarians."""
    item = make_book(visibility=Visibility.HIDDEN)

    assert not can_view(item, student)
    assert can_view(item, librarian)


def test_unilibrary_cards_need_a_login_unless_allowed(student: Actor) -> None:
    """LIB-12: anonymous cards are off by default (Q10)."""
    card = make_external()

    assert not can_view(card, None)
    assert can_view(card, student)


def test_unilibrary_records_have_no_content_and_no_notebook(student: Actor) -> None:
    """LIB-12: link-only, whatever the access class says."""
    card = make_external()

    assert not can_read_content(card, student)
    assert not can_download(card, student)
    assert not can_add_to_notebook(card, student)


def test_download_follows_the_rights_basis(student: Actor) -> None:
    """LIB-15: a file is downloaded only when its basis allows it."""
    locked = make_book(download_allowed=False)
    open_book = make_book(download_allowed=True)

    assert can_read_content(locked, student)
    assert not can_download(locked, student)
    assert can_download(open_book, student)


def test_notebooks_need_text(student: Actor) -> None:
    """LIB-10: a scan without text cannot become a notebook source."""
    scan = make_book(has_text=False)
    text = make_book(has_text=True)

    assert not can_add_to_notebook(scan, student)
    assert can_add_to_notebook(text, student)
