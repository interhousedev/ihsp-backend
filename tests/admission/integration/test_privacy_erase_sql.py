"""Erasure on PostgreSQL: every student table is emptied, nobody else is touched."""

from uuid import UUID

from app.bootstrap import common  # noqa: F401  (registers every model)
from app.modules.admission.infrastructure.orm.applications import (
    DocumentRow,
    DocumentVersionRow,
)
from app.modules.admission.infrastructure.orm.calendar import CalendarFeedRow
from app.modules.admission.infrastructure.orm.profile import ItemRow, ProfileRow
from app.modules.admission.infrastructure.staff_repositories import (
    SqlPrivacyRepository,
    _student_tables,
)
from app.shared.db.base import Base
from app.shared.ids import new_id

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

A = UUID("00000000-0000-0000-0000-0000000000a1")
B = UUID("00000000-0000-0000-0000-0000000000b1")
FILE_A = UUID("00000000-0000-0000-0000-0000000000f1")

NOT_STUDENT_DATA = frozenset(
    {
        # Reference catalog, staff and platform tables: nothing is about one student.
        # Add a table here only after deciding that, in review.
        "admission_stats",
        "aid_policies",
        "campuses",
        "career_majors",
        "career_questions",
        "costs_of_attendance",
        "deadlines",
        "eligibility_rules",
        "exam_dates",
        "facts",
        "institutions",
        "kb_articles",
        "officer_settings",
        "orgs",
        "opportunities",
        "opportunity_taxonomy",
        "places",
        "programs",
        "requirements",
        "routes",
        "runtime_settings",
        "safety_facts",
        "scholarships",
        "sources",
        "staff_assignments",
        "staff_roles",
        "staff_saved_views",
        "supp_prompts",
        "uni_web_cache",
        "test_catalog",
        "audit_events",
        "entitlements",
    }
)
"""Not erased: catalog, staff data, the audit trail and admin-granted entitlements."""


async def _seed(s: AsyncSession, student: UUID, file_id: UUID) -> None:
    s.add(ProfileRow(student_id=student, question_set_version="v1"))
    s.add(ItemRow(id=new_id(), student_id=student, kind="activity", position="Lead"))
    s.add(
        CalendarFeedRow(
            id=new_id(), user_id=student, token_hash=str(student)[-8:] * 8, locale="en"
        )
    )
    doc = new_id()
    s.add(DocumentRow(id=doc, student_id=student, kind="passport", uploaded_by=student))
    await s.flush()
    s.add(
        DocumentVersionRow(
            id=new_id(),
            document_id=doc,
            version=1,
            file_id=file_id,
            uploaded_by=student,
        )
    )
    await s.flush()


async def _count(s: AsyncSession, student: UUID, table: object) -> int:
    t = table  # type: ignore[assignment]
    col = (
        t.c.user_id if "user_id" in t.c and "student_id" not in t.c else t.c.student_id
    )
    return int(
        await s.scalar(select(func.count()).select_from(t).where(col == student)) or 0
    )


async def test_erase_empties_the_student_and_spares_others(
    db_session: AsyncSession,
) -> None:
    file_b = UUID("00000000-0000-0000-0000-0000000000f2")
    await _seed(db_session, A, FILE_A)
    await _seed(db_session, B, file_b)
    repo = SqlPrivacyRepository(db_session)
    assert await repo.stored_file_ids(A) == [FILE_A]

    counts = await repo.erase(A)

    assert {"profiles", "items", "documents", "calendar_feeds"} <= set(counts)
    for table in [*_student_tables(), CalendarFeedRow.__table__]:
        assert await _count(db_session, A, table) == 0, table.name
    assert await repo.stored_file_ids(A) == []
    assert await repo.stored_file_ids(B) == [file_b]
    assert await _count(db_session, B, ProfileRow.__table__) == 1
    assert await _count(db_session, B, ItemRow.__table__) == 1
    assert await _count(db_session, B, CalendarFeedRow.__table__) == 1


def test_every_admission_table_is_accounted_for() -> None:
    """A new table must be erased (student_id, user key, cascade) or declared."""
    admission = [t for t in Base.metadata.sorted_tables if t.schema == "admission"]
    covered = {t.name for t in _student_tables()} | {
        "calendar_feeds",
        "calendar_reminders",
        "catalog_proposals",
        "opportunity_submissions",
        "opportunity_comments",
        "opportunity_comment_reports",
    }
    changed = True
    while changed:
        changed = False
        for t in admission:
            if t.name in covered:
                continue
            for fk in (f for c in t.c for f in c.foreign_keys):
                if fk.ondelete == "CASCADE" and fk.column.table.name in covered:
                    covered.add(t.name)
                    changed = True
                    break
    rest = {t.name for t in admission} - covered
    assert rest == NOT_STUDENT_DATA, sorted(rest ^ NOT_STUDENT_DATA)
