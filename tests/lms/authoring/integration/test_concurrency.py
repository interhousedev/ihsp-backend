"""LMS-13: saving and publishing at the same moment never deadlocks.

These tests commit real data on separate connections (the rolled-back test
transaction cannot show lock behaviour), so they clean the `lms` schema up.
"""

import asyncio
from collections.abc import AsyncIterator
from uuid import UUID

from app.modules.lms.domain.authoring.enums import Visibility
from app.modules.lms.domain.authoring.errors import (
    DraftChangedError,
    DraftConflictError,
    NothingToPublishError,
)
from app.modules.lms.infrastructure.authoring.uow import SqlAuthoringUnitOfWork
from app.modules.lms.ports.authoring.unit_of_work import AuthoringUnitOfWork
from app.modules.lms.wiring_authoring import AuthoringServices, assemble_authoring
from app.shared.actor import Actor, Role
from app.shared.db.engine import make_sessionmaker
from app.shared.db.uow_testing import noop_audit_writer, noop_outbox_writer
from tests.fakes.clock import FixedClock
from tests.fakes.lms.files import FakeFilesApi
from tests.fakes.lms.identity import FakeIdentityDirectory
from tests.lms.authoring.helpers import content_of, text_block

import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

UUID_ADMIN = UUID(int=0xAD)
EXPECTED = (DraftChangedError, DraftConflictError, NothingToPublishError)


@pytest_asyncio.fixture
async def committed(
    engine: AsyncEngine, clock: FixedClock, identity: FakeIdentityDirectory
) -> AsyncIterator[AuthoringServices]:
    """Services whose transactions really commit; the lms schema is emptied after."""
    sessionmaker = make_sessionmaker(engine)

    def uow_factory() -> AuthoringUnitOfWork:
        return SqlAuthoringUnitOfWork(
            sessionmaker, noop_outbox_writer, noop_audit_writer
        )

    try:
        yield assemble_authoring(
            uow_factory, clock=clock, identity=identity, files=FakeFilesApi()
        )
    finally:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "TRUNCATE lms.test_attempts, lms.step_revisions, lms.course_steps,"
                    " lms.course_versions, lms.course_staff, lms.courses CASCADE"
                )
            )


async def test_saves_and_publishing_at_the_same_time_never_deadlock(
    committed: AuthoringServices,
) -> None:
    """The course row is locked before step rows, in saves and in publishing."""
    admin = Actor(user_id=UUID_ADMIN, roles=frozenset({Role.LMS_ADMIN}))
    course = await committed.create_course.execute(
        admin, title="Race", slug="race", visibility=Visibility.PUBLIC
    )
    section = await committed.create_section.execute(admin, course.id, "S")
    steps = [
        await committed.create_step.execute(
            admin, course.id, section_id=section.id, title=f"Step {n}"
        )
        for n in range(3)
    ]
    pending = await committed.get_pending_changes.execute(admin, course.id)
    await committed.publish_course.execute(
        admin, course.id, draft_seq=pending.draft_seq, note=None
    )

    for round_no in range(8):
        pending = await committed.get_pending_changes.execute(admin, course.id)
        current = [
            await committed.get_step_draft.execute(admin, s.step_id) for s in steps
        ]
        results = await asyncio.gather(
            committed.publish_course.execute(
                admin, course.id, draft_seq=pending.draft_seq, note=None
            ),
            *(
                committed.save_step_draft.execute(
                    admin,
                    s.step_id,
                    content_of(f"Step {n}", text_block(f"round {round_no}")),
                    s.lock_version,
                )
                for n, s in enumerate(current)
            ),
            return_exceptions=True,
        )
        unexpected = [
            r
            for r in results
            if isinstance(r, BaseException) and not isinstance(r, EXPECTED)
        ]
        assert unexpected == []

    final = await committed.get_course_draft.execute(admin, course.id)
    assert final.draft_seq >= 8
