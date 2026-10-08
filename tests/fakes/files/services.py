"""The files module assembled from fakes: real use cases, in-memory adapters."""

from dataclasses import dataclass

from app.modules.files.domain.policy import FilesLimits
from app.modules.files.infrastructure.extraction.extractor import FileTextExtractor
from app.modules.files.wiring import FilesServices, assemble
from tests.fakes.clock import FixedClock
from tests.fakes.files.resolvers import FakeTermResolver, FakeUsageResolver
from tests.fakes.files.sniffer import SignatureSniffer
from tests.fakes.files.storage import InMemoryStorage
from tests.fakes.files.uow import FakeFilesDatabase
from tests.fakes.tasks import FakeTaskKicker

GIB = 1024**3
DEFAULT_LIMITS = FilesLimits(
    student_quota_bytes=int(1.5 * GIB),
    staff_quota_bytes=10 * GIB,
    file_max_bytes=100 * 1024 * 1024,
    ai_text_max_bytes=100 * 1024,
)


@dataclass(slots=True)
class FilesFakes:
    """The assembled module and every fake behind it."""

    services: FilesServices
    db: FakeFilesDatabase
    storage: InMemoryStorage
    terms: FakeTermResolver
    usage: FakeUsageResolver
    clock: FixedClock
    kicker: FakeTaskKicker


def build_files_fakes(
    clock: FixedClock,
    kicker: FakeTaskKicker,
    *,
    limits: FilesLimits = DEFAULT_LIMITS,
) -> FilesFakes:
    """Assemble the module with in-memory storage, repository and resolvers."""
    db = FakeFilesDatabase()
    storage = InMemoryStorage()
    terms = FakeTermResolver()
    usage = FakeUsageResolver()
    services = assemble(
        uow_factory=db.uow,
        clock=clock,
        kicker=kicker,
        storage=storage,
        terms=terms,
        usage=usage,
        sniffer=SignatureSniffer(),
        extractor=FileTextExtractor(),
        limits=limits,
        closers=[],
    )
    return FilesFakes(services, db, storage, terms, usage, clock, kicker)
