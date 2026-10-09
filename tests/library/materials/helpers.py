"""Small helpers shared by the tests of the materials area."""

from uuid import UUID

from app.modules.library.application.detail import ItemDetailView


def ident(view: ItemDetailView) -> UUID:
    """The id of a stored item's detail (cards of stored items always have one)."""
    assert view.card.id is not None
    return view.card.id
