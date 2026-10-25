"""Loading and checking the parts of a label request (anything wrong is a 4xx)."""

from uuid import UUID

from app.modules.notebooks.domain.errors import InvalidOptionsError
from app.modules.notebooks.domain.label_errors import LabelNotFoundError
from app.modules.notebooks.domain.labels import (
    SourceLabel,
    clean_label_emoji,
    clean_label_name,
)
from app.modules.notebooks.ports.unit_of_work import NotebooksUnitOfWork


async def load_label(
    uow: NotebooksUnitOfWork, notebook_id: UUID, label_id: UUID
) -> SourceLabel:
    """Return a label of the notebook or raise `LabelNotFoundError`."""
    found = await uow.labels.get(label_id)
    if found is None or found.notebook_id != notebook_id:
        raise LabelNotFoundError()
    return found


def checked_name(value: object) -> str:
    """A label name of 1 to 40 characters in one line."""
    name = clean_label_name(value) if isinstance(value, str) else None
    if name is None:
        raise InvalidOptionsError(params={"field": "name"})
    return name


def checked_emoji(value: object) -> str:
    """The emoji of a label (at most 8 characters; empty means the default tag)."""
    emoji = clean_label_emoji(value) if isinstance(value, str) else None
    if emoji is None:
        raise InvalidOptionsError(params={"field": "emoji"})
    return emoji


def name_taken(labels: list[SourceLabel], name: str, except_id: UUID | None) -> bool:
    """True when another label of the list has this name (compared by case)."""
    folded = name.casefold()
    return any(
        label.name.casefold() == folded and label.id != except_id for label in labels
    )
