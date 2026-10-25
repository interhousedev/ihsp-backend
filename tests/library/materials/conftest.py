"""Fixtures of the materials area: recorded outbox/audit, files, subjects, topics."""

import dataclasses
from collections.abc import Awaitable, Callable
from typing import Any, cast
from uuid import UUID

from app.interfaces.http.dependencies import get_actor, get_optional_actor
from app.interfaces.http.v1.library.materials import ROUTERS as MATERIAL_ROUTERS
from app.modules.library.application.materials.inputs import MaterialData
from app.modules.library.domain.entities import Item
from app.modules.library.domain.enums import (
    ItemLanguage,
    ItemStatus,
    ItemType,
    MaterialLicence,
)
from app.modules.library.infrastructure.orm import Topic as TopicRow
from app.modules.library.infrastructure.uow import LibrarySqlUnitOfWork
from app.modules.library.ports.unit_of_work import LibraryUnitOfWork, UowFactory
from app.modules.library.wiring import LibraryServices, build
from app.modules.library.wiring_core import CoreOverrides
from app.settings import Settings
from app.shared.actor import Actor
from app.shared.contracts.files import FilesApi
from app.shared.contracts.identity import IdentityDirectory
from app.shared.ids import new_id
from app.shared.notifications import AuditDraft, NotificationDraft
from app.shared.wiring import ModuleDeps
from tests.conftest import HttpClientFactory
from tests.fakes.library.academic import FakeAcademicDirectory
from tests.fakes.library.identity import FakeLibraryIdentity
from tests.fakes.library.material_files import MaterialFilesApi

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@pytest.fixture
def outbox() -> list[NotificationDraft]:
    """Every notification the use cases queued and committed."""
    return []


@pytest.fixture
def audit_log() -> list[AuditDraft]:
    """Every audit event the use cases queued and committed."""
    return []


@pytest.fixture
def uow_factory(
    sessionmaker_in_tx: async_sessionmaker[AsyncSession],
    outbox: list[NotificationDraft],
    audit_log: list[AuditDraft],
) -> UowFactory:
    """SQL units of work on the test transaction that record outbox and audit."""

    async def write_outbox(
        session: AsyncSession, drafts: list[NotificationDraft]
    ) -> None:
        outbox.extend(drafts)

    async def write_audit(session: AsyncSession, drafts: list[AuditDraft]) -> None:
        audit_log.extend(drafts)

    def factory() -> LibraryUnitOfWork:
        return LibrarySqlUnitOfWork(sessionmaker_in_tx, write_outbox, write_audit)

    return factory


@pytest.fixture
def files_api() -> MaterialFilesApi:
    """In-memory files that can combine images and delete."""
    return MaterialFilesApi()


@pytest.fixture
def physics(academic: FakeAcademicDirectory) -> UUID:
    """A subject called Physics."""
    return academic.add_subject(new_id(), "Physics")


@pytest.fixture
def make_topic(
    uow_factory: UowFactory,
) -> Callable[[UUID], Awaitable[UUID]]:
    """`await make_topic(subject_id)` stores a topic and returns its id."""

    async def make(subject_id: UUID) -> UUID:
        topic_id = new_id()
        async with uow_factory() as uow:
            session = cast(LibrarySqlUnitOfWork, uow).session
            session.add(
                TopicRow(
                    id=topic_id,
                    subject_id=subject_id,
                    name={"en": "Kinematics"},
                    slug=f"kinematics-{topic_id.hex[-6:]}",
                )
            )
            await uow.commit()
        return topic_id

    return make


@pytest.fixture
def load_item(uow_factory: UowFactory) -> Callable[[UUID | None], Awaitable[Item]]:
    """`await load_item(id)` reads the stored item (fails the test when missing)."""

    async def load(item_id: UUID | None) -> Item:
        assert item_id is not None
        async with uow_factory() as uow:
            item = await uow.items.get(item_id)
        assert item is not None
        return item

    return load


@pytest.fixture
def set_status(uow_factory: UowFactory) -> Callable[..., Awaitable[None]]:
    """`await set_status(id, ItemStatus.HELD, status_reason="x")` edits the row."""

    async def change(item_id: UUID, status: ItemStatus, **fields: Any) -> None:
        async with uow_factory() as uow:
            item = await uow.items.get(item_id)
            assert item is not None
            item.status = status
            for name, value in fields.items():
                setattr(item, name, value)
            await uow.items.save(item)
            await uow.commit()

    return change


@pytest.fixture
def build_library(
    module_deps: ModuleDeps,
    settings: Settings,
    identity: FakeLibraryIdentity,
    files_api: MaterialFilesApi,
    academic: FakeAcademicDirectory,
    uow_factory: UowFactory,
) -> Callable[..., LibraryServices]:
    """`build_library(teacher_review=True)` builds the module with other settings."""

    def build_with(**overrides: Any) -> LibraryServices:
        library_settings = settings.library.model_copy(update=overrides)
        changed = dataclasses.replace(
            module_deps,
            settings=settings.model_copy(update={"library": library_settings}),
        )
        return build(
            changed,
            identity=cast(IdentityDirectory, identity),
            files=cast(FilesApi, files_api),
            academic=academic,
            overrides=CoreOverrides(uow_factory=uow_factory),
        )

    return build_with


@pytest.fixture
def material_data(physics: UUID) -> MaterialData:
    """A valid, attested material about physics."""
    return MaterialData(
        title="Kinematics cheat sheet",
        description="Formulas of uniform and accelerated motion.",
        subject_ids=(physics,),
        topic_ids=(),
        years_of_study=(1,),
        type=ItemType.FORMULA_SHEET,
        language=ItemLanguage.UZ_LATN,
        licence=MaterialLicence.ALL_RIGHTS_RESERVED,
        attested=True,
    )


@pytest.fixture
def make_draft(
    library: LibraryServices,
    files_api: MaterialFilesApi,
    material_data: MaterialData,
) -> Callable[..., Awaitable[UUID]]:
    """`await make_draft(actor, services=None, with_file=True, ...)` -> item id."""

    async def make(
        actor: Actor,
        *,
        services: LibraryServices | None = None,
        with_file: bool = True,
        **changes: Any,
    ) -> UUID:
        materials = (services or library).materials
        view = await materials.create_material.execute(
            actor, dataclasses.replace(material_data, **changes), locale="en"
        )
        assert view.card.id is not None
        if with_file:
            pdf = files_api.upload(actor.user_id)
            await materials.attach_material_files.execute(
                actor, view.card.id, [pdf], locale="en"
            )
        return view.card.id

    return make


@pytest.fixture
def make_pending(
    library: LibraryServices,
    make_draft: Callable[..., Awaitable[UUID]],
) -> Callable[..., Awaitable[UUID]]:
    """`await make_pending(student)` submits a fresh material and returns its id."""

    async def make(
        actor: Actor, *, services: LibraryServices | None = None, **kw: Any
    ) -> UUID:
        item_id = await make_draft(actor, services=services, **kw)
        await (services or library).materials.submit_material.execute(
            actor, item_id, locale="en"
        )
        return item_id

    return make


@pytest.fixture
def api(
    http_client: HttpClientFactory, library: LibraryServices
) -> Callable[[Actor | None], Awaitable[AsyncClient]]:
    """`await api(actor)` is a client logged in as the actor (None: no token)."""

    async def build(actor: Actor | None = None) -> AsyncClient:
        overrides: dict[Callable[..., Any], Callable[..., Any]] = {}
        if actor is not None:
            overrides = {get_actor: lambda: actor, get_optional_actor: lambda: actor}
        return await http_client(MATERIAL_ROUTERS, overrides, library=library)

    return build
