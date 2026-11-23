"""Course certificates on the test database with an in-memory LMS, files and names."""

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from app.modules.certificates.application.course_certificates import (
    CourseCertificates,
)
from app.modules.certificates.infrastructure.course_store import (
    SqlCourseCertificatesUnitOfWork,
)
from app.shared.contracts.course_certificates import (
    CertificateCourse,
    CertificateSection,
    LearnerResult,
    LearnerSection,
)
from app.shared.db.uow_testing import noop_audit_writer, noop_outbox_writer
from app.shared.ids import new_id
from tests.fakes.clock import FixedClock

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

NOW = datetime(2026, 12, 1, 9, 0, tzinfo=UTC)
LABEL = {"en": "Completed", "ru": "Курс пройден", "uz": "Kurs tugallandi"}
HONORS = {"en": "With honours", "ru": "С отличием", "uz": "Imtiyozli"}


@dataclass
class Facts:
    """The LMS side: one course, a manager and per-learner results."""

    course_id: UUID
    manager: UUID
    results: dict[UUID, tuple[int, int]]  # user -> (steps done of 2, points of 100)
    public: bool = True

    async def course(self, course_id: UUID) -> CertificateCourse | None:
        return CertificateCourse(
            course_id, "Physics 10", self.public, (CertificateSection("s1", "Intro"),)
        )

    async def learner(self, course_id: UUID, user_id: UUID) -> LearnerResult | None:
        if user_id not in self.results:
            return None
        done, points = self.results[user_id]
        section = LearnerSection("s1", 2, done, Decimal(100), Decimal(points))
        return LearnerResult(user_id, done * 50, (section,))

    async def active_learners(self, course_id: UUID) -> list[UUID]:
        return list(self.results)

    async def can_manage(self, user_id: UUID, course_id: UUID) -> bool:
        return user_id == self.manager


class Files:
    """In-memory files."""

    def __init__(self) -> None:
        self.data: dict[UUID, bytes] = {}

    async def store_bytes(self, **kw: Any) -> Any:  # noqa: ANN401
        file_id = new_id()
        self.data[file_id] = kw["data"]
        return type("Ref", (), {"id": file_id})()

    async def read_bytes(self, file_id: UUID) -> bytes:
        return self.data[file_id]


class Directory:
    """Names of the learners."""

    async def get_user(self, user_id: UUID) -> Any:  # noqa: ANN401
        return type("U", (), {"first_name": "Oʻgʻiloy", "last_name": "Qahhorova"})()


def make_world(
    maker: async_sessionmaker[AsyncSession],
) -> tuple[CourseCertificates, Facts]:
    """The service over ``maker`` with one course and its manager."""
    facts = Facts(new_id(), new_id(), {})
    service = CourseCertificates(
        lambda: SqlCourseCertificatesUnitOfWork(
            maker, noop_outbox_writer, noop_audit_writer
        ),
        facts,
        Files(),  # type: ignore[arg-type]
        Directory(),  # type: ignore[arg-type]
        FixedClock(NOW),
        "https://lms.example",
    )
    return service, facts


async def enable(service: CourseCertificates, facts: Facts) -> None:
    """Turn certificates on: 60 % to pass, honours from 90 %."""
    template = await service.create_template(facts.manager, facts.course_id, "Main")
    await service.put_settings(
        facts.manager,
        facts.course_id,
        {
            "enabled": True,
            "passing_pct": 60,
            "tiers": [
                {"key": "normal", "label": LABEL},
                {"key": "honors", "label": HONORS, "min_pct": 90},
            ],
            "template_id": str(template.id),
        },
    )
