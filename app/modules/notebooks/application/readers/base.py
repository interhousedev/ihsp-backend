"""What every source reader provides: adding checks and the text itself (§ 3.2.1)."""

from dataclasses import dataclass, field
from typing import Any, Protocol, TypeVar
from uuid import UUID

from app.modules.notebooks.domain.entities import Source
from app.modules.notebooks.domain.enums import SourceKind
from app.modules.notebooks.domain.errors import SourceUnsupportedError
from app.modules.notebooks.domain.limits import SOURCE_TITLE_MAX_CHARS
from app.modules.notebooks.domain.source_input import SourceInput

InputT = TypeVar("InputT")


@dataclass(frozen=True, slots=True)
class ResolvedSource:
    """What `resolve` found out at add time: the row to store, without its text.

    `body_md` is set for pasted text and notes only (their text lives in the row).
    """

    kind: SourceKind
    title: str
    ref: dict[str, Any]
    ref_key: str | None
    origin: dict[str, Any] | None = None
    body_md: str | None = None


@dataclass(frozen=True, slots=True)
class SourceText:
    """The text of a source at process time.

    Attributes:
        text: Raw text; the pipeline normalises and chunks it.
        page_starts: Offset where each page starts in `text`.
        unit_starts: Offsets of units that must not be merged (chat pairs, ...).
        upstream_version: Version of the upstream object that was read.
        ref_update: Keys merged into the source's `ref` after reading.
    """

    text: str
    page_starts: tuple[int, ...] = ()
    unit_starts: tuple[int, ...] = ()
    upstream_version: str | None = None
    ref_update: dict[str, Any] = field(default_factory=dict)


class SourceReader(Protocol):
    """One implementation per source kind."""

    async def resolve(self, user_id: UUID, source_input: SourceInput) -> ResolvedSource:
        """Check that the user may use the object and describe the new source.

        Raises:
            SourceForbiddenError: Not the user's object, or it does not exist.
            SourceUnsupportedError: The object has no text or is of a wrong type.
        """
        ...

    async def read(self, source: Source) -> SourceText:
        """Read the current text of the source.

        Raises:
            SourceReadError: With the failure code (`deleted`, `forbidden`, ...).
        """
        ...


class VersionedReader(SourceReader, Protocol):
    """A reader whose upstream object can change after the snapshot (sweep)."""

    async def current_version(self, source: Source) -> str | None:
        """The upstream version now; None when it cannot be found out cheaply."""
        ...


def expect_input(source_input: SourceInput, wanted: type[InputT]) -> InputT:
    """Return the input as the kind the reader handles.

    Raises:
        SourceUnsupportedError: The input is of another kind (a wiring mistake).
    """
    if not isinstance(source_input, wanted):
        raise SourceUnsupportedError(params={"hint": "kind"})
    return source_input


def clean_title(title: str | None, fallback: str) -> str:
    """One line of at most 255 characters; `fallback` when the title is empty."""
    flat = " ".join((title or "").split())
    return (flat or fallback)[:SOURCE_TITLE_MAX_CHARS]
