"""Source kinds `text` and `note`: the text lives in the row's `body_md`."""

from uuid import UUID

from app.modules.notebooks.application.readers.base import (
    ResolvedSource,
    SourceText,
    clean_title,
    expect_input,
)
from app.modules.notebooks.domain.entities import Source
from app.modules.notebooks.domain.enums import SourceKind
from app.modules.notebooks.domain.errors import InvalidOptionsError
from app.modules.notebooks.domain.source_input import NoteInput, SourceInput, TextInput


class TextReader:
    """Pasted text and notes; the stored `body_md` is the source of truth."""

    async def resolve(self, user_id: UUID, source_input: SourceInput) -> ResolvedSource:
        """Describe a pasted text or a note (no access check: it is the user's own).

        Raises:
            InvalidOptionsError: The title or the text is blank.
        """
        if isinstance(source_input, NoteInput):
            kind, raw_title, body = (
                SourceKind.NOTE,
                source_input.title,
                source_input.body_md,
            )
        else:
            item = expect_input(source_input, TextInput)
            kind, raw_title, body = SourceKind.TEXT, item.title, item.text
        title = clean_title(raw_title, "")
        if not title or not body.strip():
            field = "title" if not title else "text"
            raise InvalidOptionsError(params={"field": field})
        return ResolvedSource(
            kind=kind, title=title, ref={}, ref_key=None, body_md=body
        )

    async def read(self, source: Source) -> SourceText:
        """Return the stored body."""
        return SourceText(text=source.body_md or "")
