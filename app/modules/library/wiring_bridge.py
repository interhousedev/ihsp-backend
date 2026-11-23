"""Builds the bridge area of the library: books and materials as notebook sources."""

from dataclasses import dataclass

from app.modules.library.application.bridge.book_catalogue import (
    LibraryBookCatalogueImpl,
)
from app.modules.library.application.bridge.source_reader import (
    LibrarySourceReaderImpl,
)
from app.modules.library.wiring_core import LibraryCore
from app.shared.contracts.library import LibraryBookCatalogue, LibrarySourceReader


@dataclass(frozen=True, slots=True)
class BridgeServices:
    """Use cases of the bridge area (fields are added by the area)."""

    source_reader: LibrarySourceReader  # the notebooks module's way in (LIB-10)
    book_catalogue: LibraryBookCatalogue  # published books for admission courses


def build_bridge(core: LibraryCore) -> BridgeServices:
    """Wire the use cases of the bridge area."""
    return BridgeServices(
        source_reader=LibrarySourceReaderImpl(
            uow_factory=core.uow_factory, files=core.files
        ),
        book_catalogue=LibraryBookCatalogueImpl(
            uow_factory=core.uow_factory,
            cards=core.cards,
            identity=core.identity,
            settings=core.settings,
        ),
    )
