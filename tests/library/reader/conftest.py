"""Fixtures of the reader state tests: the area over fakes on the test transaction."""

from uuid import UUID

from app.modules.library.domain.entities import Item
from app.modules.library.domain.enums import ItemStatus, Visibility
from app.modules.library.wiring import LibraryServices
from app.modules.library.wiring_reader import ReaderServices, build_reader
from app.shared.ids import new_id
from tests.factories.library import make_book, make_external, make_material
from tests.fakes.library.academic import FakeAcademicDirectory
from tests.fakes.library.lessons import FakeLessonDirectory
from tests.library.reader.helpers import StoreItem

import pytest
import pytest_asyncio

@pytest.fixture
def lessons() -> FakeLessonDirectory:
    """Lessons configured by the test."""
    return FakeLessonDirectory()


@pytest.fixture
def reader(library: LibraryServices, lessons: FakeLessonDirectory) -> ReaderServices:
    """The reader area with the fake lesson directory."""
    return build_reader(library.core, lessons=lessons)


@pytest_asyncio.fixture
async def book(store_item: StoreItem) -> Item:
    """A published lyceum book with text that every signed-in user may read."""
    return await store_item(make_book(title="Physics 10"))


@pytest_asyncio.fixture
async def material(store_item: StoreItem) -> Item:
    """A published lyceum material."""
    return await store_item(make_material(title="Kinematics notes"))


@pytest_asyncio.fixture
async def external(store_item: StoreItem) -> Item:
    """A stored UniLibrary record (link only)."""
    return await store_item(make_external())


@pytest_asyncio.fixture
async def taken_down(store_item: StoreItem) -> Item:
    """A book a librarian took down."""
    return await store_item(make_book(title="Removed", status=ItemStatus.UNPUBLISHED))


@pytest_asyncio.fixture
async def hidden(store_item: StoreItem) -> Item:
    """A published book a librarian hid."""
    return await store_item(make_book(title="Hidden", visibility=Visibility.HIDDEN))


@pytest.fixture
def subject(academic: FakeAcademicDirectory) -> UUID:
    """A subject the academic fake knows."""
    return academic.add_subject(new_id(), "Physics")
