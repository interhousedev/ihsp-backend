"""Library books and materials as sources: titles, keys and the notes text (LIB-10).

Pure rules. The reader of the kinds `library_item` and `library_notes` builds the
title and keys with these functions, and the source pipeline derives the shared
document alias from the same key, so one chapter read by thirty students is
processed once.
"""

import hashlib
from collections.abc import Sequence
from uuid import UUID

from app.modules.notebooks.domain.limits import SOURCE_TITLE_MAX_CHARS
from app.shared.contracts.library import LibraryAnnotationRef

NOTES_HEADING = "Highlights and notes"
VERSION_CHARS = 32


def pages_label(page_from: int | None, page_to: int | None) -> str:
    """`pp. 54-61`, `p. 54` or `from p. 54`; empty when no range was asked for."""
    if page_from is None and page_to is None:
        return ""
    if page_to is None:
        return f"from p. {page_from}"
    first = page_from or 1
    return f"p. {first}" if first == page_to else f"pp. {first}-{page_to}"


def library_title(title: str, page_from: int | None, page_to: int | None) -> str:
    """`Physics 10, pp. 54-61`: the title is cut so that the pages always fit."""
    label = pages_label(page_from, page_to)
    suffix = f", {label}" if label else ""
    flat = " ".join(title.split())
    return flat[: SOURCE_TITLE_MAX_CHARS - len(suffix)].rstrip() + suffix


def library_key(file_id: UUID, page_from: int | None, page_to: int | None) -> str:
    """Names the text of a file range; `0` as the last page means "to the end"."""
    return f"library:{file_id}:{page_from or 1}:{page_to or 0}"


def notes_key(item_id: UUID) -> str:
    """Names the notes source of a book (one per notebook)."""
    return f"library-notes:{item_id}"


def _flat(text: str | None) -> str:
    """One line: whitespace runs, blank lines included, become single spaces."""
    return " ".join((text or "").split())


def _in_reading_order(
    notes: Sequence[LibraryAnnotationRef],
) -> list[LibraryAnnotationRef]:
    """By page, then by time; annotations without a page come last."""
    return sorted(notes, key=lambda n: (n.page is None, n.page or 0, n.updated_at))


def _block(note: LibraryAnnotationRef) -> str:
    """`> quote (p. N)` and the student's note on the next line; empty if no words."""
    quote, words = _flat(note.quote), _flat(note.note)
    where = f" (p. {note.page})" if note.page is not None else ""
    if quote:
        return f"> {quote}{where}" + (f"\n{words}" if words else "")
    return f"{words}{where}" if words else ""


def render_notes(title: str, notes: Sequence[LibraryAnnotationRef]) -> str:
    """The student's highlights and notes as Markdown; empty when there are none."""
    blocks = [block for n in _in_reading_order(notes) if (block := _block(n))]
    if not blocks:
        return ""
    heading = f"# {NOTES_HEADING}: {_flat(title)}"
    return "\n\n".join([heading, *blocks]) + "\n"


def notes_version(notes: Sequence[LibraryAnnotationRef]) -> str:
    """A fingerprint of the annotations: changes on an edit, a new or a deleted one."""
    lines = sorted(
        "|".join(
            (
                n.kind,
                n.quote or "",
                n.note or "",
                str(n.page),
                n.color,
                n.updated_at.isoformat(),
            )
        )
        for n in notes
    )
    digest = hashlib.sha256("\n".join(lines).encode()).hexdigest()
    return digest[:VERSION_CHARS]
