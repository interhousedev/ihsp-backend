"""Who may see what through a share, and how link tokens are stored."""

from app.modules.notebooks.domain.enums import NotebookOrigin, SourceKind
from app.modules.notebooks.domain.sharing import (
    hash_token,
    is_shareable,
    new_token,
    viewable,
)
from tests.factories.notebooks import NOW, new_notebook_entity, new_source_entity

import pytest


@pytest.mark.parametrize("origin", list(NotebookOrigin))
def test_only_a_manual_notebook_is_shareable(origin: NotebookOrigin) -> None:
    """NB-SHARE: auto, course and hidden notebooks hold gated material."""
    notebook = new_notebook_entity(origin=origin)

    assert is_shareable(notebook) is (origin is NotebookOrigin.MANUAL)


def test_a_deleted_notebook_is_not_shareable() -> None:
    """NB-SHARE: deleting ends every share at once."""
    assert not is_shareable(new_notebook_entity(deleted_at=NOW))


@pytest.mark.parametrize(
    ("kind", "shown"),
    [
        (SourceKind.FILE, True),
        (SourceKind.TEXT, True),
        (SourceKind.NOTE, True),
        (SourceKind.URL, True),
        (SourceKind.WEB_RESULT, True),
        (SourceKind.CHAT, False),
        (SourceKind.LESSON_RESOURCE, False),
        (SourceKind.FLASHCARD_SET, False),
        (SourceKind.LMS_STEP, False),
        (SourceKind.LIBRARY_ITEM, False),
        (SourceKind.LIBRARY_NOTES, False),
    ],
)
def test_private_and_gated_kinds_stay_out_of_the_shared_view(
    kind: SourceKind, shown: bool
) -> None:
    """NB-SHARE: a share never widens a chat, lesson, course or library audience."""
    source = new_source_entity(new_notebook_entity(), kind=kind)

    assert bool(viewable([source])) is shown


def test_a_token_is_long_and_stored_only_as_a_hash() -> None:
    """NB-SHARE: a database dump does not open any link."""
    token = new_token()

    assert len(token) >= 43
    assert token not in hash_token(token)
    assert hash_token(token) == hash_token(token)
    assert len(hash_token(token)) == 64
