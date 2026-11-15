"""Give a book without a cover one cut out of its primary file."""

import asyncio

from app.modules.library.application.catalogue.cover_extract import extract_cover
from app.modules.library.domain.entities import Item, ItemFile
from app.modules.library.domain.enums import ItemKind
from app.shared.base_error import BaseError
from app.shared.contracts.files import FilePurpose, FilesApi, FileScope

import structlog

log = structlog.get_logger(__name__)


def needs_cover(item: Item, stored: ItemFile) -> bool:
    """A book's primary file may give it a cover only while it has none."""
    return (
        stored.is_primary
        and item.kind is ItemKind.BOOK
        and not item.cover_file_id
        and not item.cover_url
    )


async def make_cover(files: FilesApi, item: Item, stored: ItemFile) -> bool:
    """Set `item.cover_file_id` from the file; True when a cover was made.

    Never replaces a cover that is already set and never raises: a file without a
    usable first image just keeps the placeholder.
    """
    if not needs_cover(item, stored):
        return False
    try:
        ref = await files.get(stored.file_id)
        owner_id = item.owner_id or (ref.owner_id if ref else None)
        if owner_id is None:
            return False
        data = await files.read_bytes(stored.file_id)
        found = await asyncio.to_thread(extract_cover, data, stored.format)
        if found is None:
            return False
        image, name = found
        cover = await files.store_bytes(
            owner_id=owner_id,
            scope=FileScope.LIBRARY,
            purpose=FilePurpose.LIBRARY_COVER,
            name=name,
            data=image,
        )
    except BaseError as error:
        log.warning("library_cover_failed", code=error.code)
        return False
    item.cover_file_id = cover.id
    return True
