"""Fixtures of the bridge tests: the reader over the SQL unit of work."""

import datetime as dt
from collections.abc import Awaitable, Callable
from typing import Any, cast
from uuid import UUID

from app.modules.library.application.bridge.source_reader import (
    LibrarySourceReaderImpl,
)
from app.modules.library.domain.entities import Item
from app.modules.library.domain.enums import AnnotationColor, AnnotationKind, ItemStatus
from app.modules.library.domain.reader_annotation import build_annotation, soft_delete
from app.modules.library.ports.unit_of_work import UowFactory
from app.shared.actor import Actor
from app.shared.contracts.files import FilesApi
from app.shared.ids import new_id
from tests.factories.library import make_book
from tests.fakes.library.files import FakeFilesApi

import pytest

AddBook = Callable[..., Awaitable[Item]]
StoreItem = Callable[[Item], Awaitable[Item]]
NOW = dt.datetime(2026, 10, 6, 9, 0, tzinfo=dt.UTC)
AddNote = Callable[..., Awaitable[None]]
SetStatus = Callable[[Item, ItemStatus], Awaitable[None]]


@pytest.fixture
def visitor(make_actor: Callable[..., Actor]) -> Actor:
    """Someone without any role: not signed in to the lyceum."""
    return make_actor()


@pytest.fixture
def reader(uow_factory: UowFactory, files_api: FakeFilesApi) -> LibrarySourceReaderImpl:
    """The bridge reader over the test transaction."""
    return LibrarySourceReaderImpl(
        uow_factory=uow_factory, files=cast(FilesApi, files_api)
    )


@pytest.fixture
def add_note(uow_factory: UowFactory) -> AddNote:
    """Store an annotation of a user on an item through the reader area's repository."""

    async def add(
        user_id: UUID,
        item_id: UUID,
        *,
        kind: AnnotationKind = AnnotationKind.HIGHLIGHT,
        quote: str | None = "Newton's first law",
        note: str | None = None,
        locator: dict[str, Any] | None = None,
        minutes: int = 0,
        deleted: bool = False,
    ) -> None:
        moment = NOW + dt.timedelta(minutes=minutes)
        annotation = build_annotation(
            user_id=user_id,
            item_id=item_id,
            file_id=new_id(),
            kind=kind,
            locator={"page": 2} if locator is None else locator,
            quote=quote,
            note=note,
            color=AnnotationColor.YELLOW,
            client_id=new_id(),
            now=moment,
        )
        if deleted:
            annotation = soft_delete(annotation, now=moment)
        async with uow_factory() as uow:
            assert await uow.annotations.add(annotation)
            if deleted:
                await uow.annotations.save(annotation)
            await uow.commit()

    return add


@pytest.fixture
def add_book(files_api: FakeFilesApi, store_item: StoreItem) -> AddBook:
    """Store a published book whose file has the given page texts."""

    async def add(*pages: str, **fields: Any) -> Item:  # fields: make_book's
        file_id = files_api.add_file(owner_id=new_id(), pages=pages)
        return await store_item(make_book(file_id=file_id, **fields))

    return add


@pytest.fixture
def set_status(uow_factory: UowFactory) -> SetStatus:
    """Change the status of a stored item (a hold, a takedown, a restore)."""

    async def change(item: Item, status: ItemStatus) -> None:
        async with uow_factory() as uow:
            stored = await uow.items.get(item.id)
            assert stored is not None
            stored.status = status
            await uow.items.save(stored)
            await uow.commit()

    return change
