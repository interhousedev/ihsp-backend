"""Fixtures of the certificates tests: the module wired to in-memory fakes."""

from collections.abc import Callable
from dataclasses import dataclass, field
from uuid import UUID

from app.modules.certificates.domain.certificate_type import CertificateType
from app.modules.certificates.ports.student_directory import StudentInfo
from app.modules.certificates.wiring import (
    CertificatesOverrides,
    CertificatesServices,
    build,
)
from app.settings import Settings
from app.shared.actor import Actor, Role
from app.shared.db.uow_testing import noop_audit_writer, noop_outbox_writer
from app.shared.i18n.core import I18nCore
from app.shared.ids import new_id
from app.shared.rate_limit import RateLimiter
from app.shared.wiring import ModuleDeps
from tests.fakes.certificates.uow import FakeCertificatesStore, fake_uow_factory
from tests.fakes.certificates.world import (
    FakeDirectory,
    FakeEmis,
    FakeFetcher,
    FakeFiles,
)
from tests.fakes.clock import FixedClock
from tests.fakes.tasks import FakeTaskKicker

import pytest
from fakeredis.aioredis import FakeRedis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


def make_type(code: str = "ielts", **fields: object) -> CertificateType:
    """A type entity; the name is the code in the three languages."""
    values: dict[str, object] = {
        "id": new_id(),
        "code": code,
        "name": {"uz": code, "ru": code, "en": code},
    }
    values.update(fields)
    return CertificateType(**values)  # type: ignore[arg-type]


def make_student(
    name: str, group_id: UUID, group_name: str, subgroup: str | None = None
) -> StudentInfo:
    """A student of a group."""
    return StudentInfo(new_id(), name, group_id, group_name, subgroup)


@dataclass
class CertificatesHarness:
    """The wired module with every fake reachable for arrangement and assertions."""

    services: CertificatesServices
    store: FakeCertificatesStore
    files: FakeFiles
    directory: FakeDirectory
    emis: FakeEmis
    fetcher: FakeFetcher
    admin: Actor
    curator: Actor
    other_curator: Actor
    group_a: UUID = field(default_factory=new_id)
    group_b: UUID = field(default_factory=new_id)
    ann: StudentInfo = field(init=False)
    bob: StudentInfo = field(init=False)
    cid: StudentInfo = field(init=False)

    def __post_init__(self) -> None:
        """Two students in group A (halves 1 and 2) and one in group B."""
        self.ann = make_student("Ann Alpha", self.group_a, "2TN1", "1")
        self.bob = make_student("Bob Beta", self.group_a, "2TN1", "2")
        self.cid = make_student("Cid Gamma", self.group_b, "2TN2", "1")
        self.directory.students_list = [self.ann, self.bob, self.cid]
        self.directory.curators = {
            self.curator.user_id: [self.group_a],
            self.other_curator.user_id: [self.group_b],
        }

    def student_actor(self, student: StudentInfo) -> Actor:
        """An actor that is the student."""
        return Actor(user_id=student.id, roles=frozenset({Role.STUDENT}))

    async def add_type(self, code: str = "ielts", **fields: object) -> CertificateType:
        """Put a type into the store."""
        kind = make_type(code, **fields)
        self.store.types[kind.id] = kind
        return kind

    async def add_entry(
        self, student: StudentInfo, kind: CertificateType, **values: object
    ) -> UUID:
        """Create an entry for the student and return its id."""
        entry = await self.services.create_entry.execute(student.id, kind.id, values)
        return entry.id

    async def add_file(
        self, student: StudentInfo, entry_id: UUID, name: str = "scan.pdf"
    ) -> UUID:
        """Attach a file to the student's entry and return the file id."""
        file = await self.services.add_entry_file.execute(
            student.id, entry_id, name=name, data=b"data"
        )
        return file.id


@pytest.fixture
def h(
    settings: Settings,
    i18n: I18nCore,
    redis: FakeRedis,
    clock: FixedClock,
    kicker: FakeTaskKicker,
    make_actor: Callable[..., Actor],
) -> CertificatesHarness:
    """The module on in-memory fakes, with an admin and two curators."""
    store = FakeCertificatesStore()
    files, directory, emis, fetcher = (
        FakeFiles(),
        FakeDirectory(),
        FakeEmis(),
        FakeFetcher(),
    )
    deps = ModuleDeps(
        settings=settings,
        clock=clock,
        redis=redis,
        sessionmaker=async_sessionmaker(class_=AsyncSession),
        kicker=kicker,
        rate_limiter=RateLimiter(redis),
        i18n=i18n,
        outbox_writer=noop_outbox_writer,
        audit_writer=noop_audit_writer,
        outbox_committed_hook=None,
    )
    services = build(
        deps,
        files=files,  # type: ignore[arg-type]
        emis=emis,  # type: ignore[arg-type]
        directory=directory,
        overrides=CertificatesOverrides(
            uow_factory=fake_uow_factory(store), fetcher=fetcher
        ),
    )
    return CertificatesHarness(
        services=services,
        store=store,
        files=files,
        directory=directory,
        emis=emis,
        fetcher=fetcher,
        admin=make_actor(Role.ADMIN),
        curator=make_actor(Role.TEACHER),
        other_curator=make_actor(Role.TEACHER),
    )
