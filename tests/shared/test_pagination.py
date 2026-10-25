"""Cursor pagination."""

from app.shared.base_error import ValidationFailedError
from app.shared.pagination import Page, decode_cursor, encode_cursor

import pytest


def test_cursor_round_trips() -> None:
    """The cursor is opaque but carries the data back."""
    data = {"id": "abc", "n": 5}

    assert decode_cursor(encode_cursor(data)) == data


@pytest.mark.parametrize("empty", [None, ""])
def test_no_cursor_means_the_first_page(empty: str | None) -> None:
    """A missing cursor starts at the beginning."""
    assert decode_cursor(empty) is None


@pytest.mark.parametrize("broken", ["!!!", "bm90LWpzb24=", "Ж"])
def test_a_broken_cursor_is_a_validation_error(broken: str) -> None:
    """A client-made garbage cursor is a 422, not a crash."""
    with pytest.raises(ValidationFailedError):
        decode_cursor(broken)


def test_page_serializes_items_and_next_cursor() -> None:
    """Page<T> = {items, next_cursor}."""
    page = Page[int](items=[1, 2])

    assert page.model_dump() == {"items": [1, 2], "next_cursor": None}


def test_a_cursor_that_is_not_an_object_is_rejected() -> None:
    """Only the JSON objects we encode are accepted."""
    with pytest.raises(ValidationFailedError):
        decode_cursor("WzFd")  # base64 of [1]
