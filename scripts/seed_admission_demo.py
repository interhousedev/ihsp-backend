"""Seed admission demo data (idempotent, dev only).

IHSP_ENV_FILE=materials/dev.env uv run python scripts/seed_admission_demo.py

Creates sign-in accounts (password sign-in through iht.id / Hydra) for the roles
student, counselor, mentor, transcript_officer, admin and teacher, the staff
caseload assignments, a catalog subset, activity items and a transcript request.
Passwords are fixed dev-only `Demo...` values; nothing here is a real secret.
"""

import asyncio
import sys
from typing import cast
from uuid import NAMESPACE_URL, UUID, uuid5

from app.bootstrap.common import build_container
from app.bootstrap.container import Container
from app.bootstrap.seed.users import _ensure
from app.modules.admission.application.checklist import ensure_all
from app.modules.admission.infrastructure.catalog_loader import load_catalog
from app.modules.admission.infrastructure.chooser_repositories import (
    SqlListRepository,
)
from app.modules.admission.infrastructure.documents_repositories import (
    SqlChecklistRepository,
    SqlDeadlineRepository,
)
from app.modules.admission.infrastructure.orm.access import (
    EntitlementRow,
    StaffAssignmentRow,
    StaffRoleRow,
)
from app.modules.admission.infrastructure.orm.applications import (
    ChecklistItemRow,
    ListEntryRow,
    TranscriptRequestRow,
)
from app.modules.admission.infrastructure.orm.catalog import InstitutionRow
from app.modules.admission.infrastructure.orm.profile import ItemRow
from app.modules.admission.ports.unit_of_work import AdmissionUnitOfWork
from app.settings import load_settings
from app.shared.actor import Role
from app.shared.logging import configure_logging

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

PASSWORD = "DemoAdmission1"
_NS = uuid5(NAMESPACE_URL, "admission.demo.seed")

# (key, login, first, last, roles, built-in staff role key)
ACCOUNTS = (
    ("student", "demo.student", "Aziza", "Demo", {Role.STUDENT}, None),
    (
        "counselor",
        "demo.counselor",
        "Dilnoza",
        "Counselor",
        {Role.COUNSELOR},
        "counselor_full",
    ),
    ("mentor", "demo.mentor", "Timur", "Mentor", {Role.MENTOR}, "student_counselor"),
    (
        "transcript_officer",
        "demo.officer",
        "Gulnora",
        "Officer",
        {Role.TRANSCRIPT_OFFICER},
        "transcript_officer",
    ),
    ("admin", "demo.admin", "Admin", "Demo", {Role.ADMIN}, None),
    ("teacher", "demo.teacher", "Bobur", "Teacher", {Role.TEACHER}, None),
)

ITEMS = (
    (
        "activity",
        "Founder",
        "Robotics club",
        "Built and led a 12-person team.",
        4,
        "stem_research",
    ),
    (
        "activity",
        "Volunteer",
        "Tashkent food bank",
        "Weekly food packing shifts.",
        2,
        "leadership_service",
    ),
    (
        "honor",
        "Gold medal",
        "Republic Math Olympiad",
        "Regional gold medal.",
        0,
        "national",
    ),
)


def out(line: str) -> None:
    """Write a line to stdout."""
    sys.stdout.write(line + "\n")


async def _assign(
    s: AsyncSession, ids: dict[str, UUID], role_ids: dict[str, UUID]
) -> None:
    for key, *_rest, role_key in ACCOUNTS:
        if role_key is None:
            continue
        row_id = uuid5(_NS, f"assignment:{key}")
        if await s.get(StaffAssignmentRow, row_id) is None:
            s.add(
                StaffAssignmentRow(
                    id=row_id,
                    user_id=ids[key],
                    staff_role_id=role_ids[role_key],
                    scope_kind="student",
                    scope_ref=ids["student"],
                    granted_by=ids["admin"],
                    granted_via="admin",
                )
            )


async def _items(s: AsyncSession, student: UUID) -> None:
    for n, (kind, position, org, desc, hours, category) in enumerate(ITEMS):
        item_id = uuid5(_NS, f"item:{n}")
        existing = await s.get(ItemRow, item_id)
        if existing is not None:
            if existing.category is None:
                existing.category = category
        else:
            s.add(
                ItemRow(
                    id=item_id,
                    student_id=student,
                    kind=kind,
                    category=category,
                    position=position,
                    org=org,
                    description=desc,
                    hours_week=hours or None,
                    weeks_year=30 if hours else None,
                    grade_levels=[10, 11],
                    sort_order=n,
                )
            )


async def _transcript(s: AsyncSession, student: UUID) -> None:
    req_id = uuid5(_NS, "transcript-request")
    has_open = await s.scalar(
        select(TranscriptRequestRow.id).where(
            TranscriptRequestRow.student_id == student,
            TranscriptRequestRow.status == "requested",
        )
    )
    if has_open is None and await s.get(TranscriptRequestRow, req_id) is None:
        s.add(
            TranscriptRequestRow(
                id=req_id,
                student_id=student,
                destination_note="Demo: for Stanford University",
                status="requested",
            )
        )


class _ChecklistUow:
    """The two repositories checklist generation needs, over one session."""

    def __init__(self, s: AsyncSession) -> None:
        self.checklist = SqlChecklistRepository(s)
        self.deadlines = SqlDeadlineRepository(s)
        self.shortlist = SqlListRepository(s)


# template key -> (important, urgent): one group per Eisenhower quadrant.
PRIORITIES = {
    "entry.application_form": (True, True),
    "shared.transcript": (True, True),
    "entry.essay": (True, False),
    "shared.translation": (True, False),
    "entry.fee": (False, True),
    "entry.recommendation": (False, False),
}


async def _checklist(s: AsyncSession, student: UUID) -> None:
    """One list entry (the first published institution), then generate the rows."""
    entry_id = uuid5(_NS, "list-entry")
    inst = await s.scalar(
        select(InstitutionRow.id)
        .where(InstitutionRow.status == "published")
        .order_by(InstitutionRow.name)
        .limit(1)
    )
    if inst is not None and await s.get(ListEntryRow, entry_id) is None:
        has = await s.scalar(
            select(ListEntryRow.id).where(
                ListEntryRow.student_id == student,
                ListEntryRow.institution_id == inst,
            )
        )
        if has is None:
            s.add(
                ListEntryRow(
                    id=entry_id, student_id=student, institution_id=inst, round="RD"
                )
            )
            await s.flush()
    await ensure_all(cast("AdmissionUnitOfWork", _ChecklistUow(s)), student)
    for key, (important, urgent) in PRIORITIES.items():
        await s.execute(
            update(ChecklistItemRow)
            .where(
                ChecklistItemRow.student_id == student,
                ChecklistItemRow.template_key == key,
                ChecklistItemRow.status != "done",
            )
            .values(important=important, urgent_override=urgent)
        )


async def seed(container: Container) -> dict[str, UUID]:
    """Create everything; running it again adds nothing."""
    ids: dict[str, UUID] = {}
    for key, login, first, last, roles, _ in ACCOUNTS:
        ids[key] = await _ensure(
            container,
            login=login,
            first_name=first,
            last_name=last,
            password=PASSWORD,
            roles=set(roles),
        )
    now = container.clock.now()
    student = ids["student"]
    async with container.sessionmaker() as s:
        await load_catalog(s, now)
        if await s.get(EntitlementRow, student) is None:
            s.add(EntitlementRow(user_id=student, kind="school_student"))
        role_ids = {
            r.key: r.id for r in (await s.scalars(select(StaffRoleRow))).all() if r.key
        }
        await _assign(s, ids, role_ids)
        await _items(s, student)
        await _transcript(s, student)
        await _checklist(s, student)
        await s.commit()
    return ids


async def _run() -> None:
    from app.interfaces.jobs.broker import broker

    settings = load_settings()
    configure_logging(settings.log_level, json_logs=False)
    await broker.startup()
    container = await build_container(settings, process="identity")
    try:
        await seed(container)
    finally:
        await container.close()
        await broker.shutdown()


def main() -> int:
    """Run the seed and print the demo logins."""
    asyncio.run(_run())
    out("Admission demo accounts (dev only, password sign-in via iht.id):")
    for key, login, *_ in ACCOUNTS:
        out(f"  {key:<20} {login} / {PASSWORD}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
