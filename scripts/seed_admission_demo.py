"""Seed admission demo data (idempotent, dev only).

IHSP_ENV_FILE=materials/dev.env uv run python scripts/seed_admission_demo.py

Creates sign-in accounts (password sign-in through iht.id / Hydra) for the roles
student, counselor, mentor, transcript_officer, admin and teacher, the staff
caseload assignments, a catalog subset, activity items and a transcript request.
Passwords are fixed dev-only `Demo...` values; nothing here is a real secret.
"""

import asyncio
import sys
from dataclasses import replace
from typing import cast
from uuid import NAMESPACE_URL, UUID, uuid5

from app.bootstrap.common import build_container
from app.bootstrap.container import Container
from app.bootstrap.seed.users import _ensure
from app.modules.admission.application.checklist import ensure_all
from app.modules.admission.domain.errors import EssayKeyUnavailableError
from app.modules.admission.domain.essay_flow import PromptTarget
from app.modules.admission.domain.essays import Essay
from app.modules.admission.infrastructure.catalog_loader import load_catalog
from app.modules.admission.infrastructure.chooser_repositories import (
    SqlListRepository,
)
from app.modules.admission.infrastructure.documents_repositories import (
    SqlChecklistRepository,
    SqlDeadlineRepository,
)
from app.modules.admission.infrastructure.essay_crypto import essay_cipher
from app.modules.admission.infrastructure.essays_repository import SqlEssayRepository
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
from app.modules.admission.infrastructure.orm.profile import EssayRow, ItemRow
from app.modules.admission.infrastructure.orm.supp_prompts import SuppPromptRow
from app.modules.admission.ports.unit_of_work import AdmissionUnitOfWork
from app.settings import load_settings
from app.shared.actor import Role
from app.shared.contracts.identity import UserStatus
from app.shared.logging import configure_logging

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

PASSWORD = "DemoAdmission1"
_NS = uuid5(NAMESPACE_URL, "admission.demo.seed")

# (key, login, first, last, roles, built-in staff role key)
ACCOUNTS = (
    ("student", "demo.student", "Aziza", "Demo", {Role.STUDENT}, None),
    # Undecided: no list, no field, no essays, no activities (nothing below attaches data to it).
    ("undecided", "demo.undecided", "Sardor", "Demo", {Role.STUDENT}, None),
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


LISTED = ("harvard", "yale", "mit", "stanford")
"""Schools with seed supplemental prompts, so the essay groups have content."""


async def _list_entry(s: AsyncSession, student: UUID, key: str, inst: UUID) -> None:
    """Add a list entry for `inst` unless the student already lists it."""
    entry_id = uuid5(_NS, key)
    if await s.get(ListEntryRow, entry_id) is not None:
        return
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


async def _checklist(s: AsyncSession, student: UUID) -> None:
    """List entries (the first published institution and `LISTED`), then the rows."""
    inst = await s.scalar(
        select(InstitutionRow.id)
        .where(InstitutionRow.status == "published")
        .order_by(InstitutionRow.name)
        .limit(1)
    )
    if inst is not None:
        await _list_entry(s, student, "list-entry", inst)
    for slug in LISTED:
        found = await s.scalar(
            select(InstitutionRow.id).where(InstitutionRow.slug == slug)
        )
        if found is not None:
            await _list_entry(s, student, f"list-entry:{slug}", found)
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


ESSAY_TEXTS = (
    (
        "Why robotics",
        "Building the robot taught me to test every idea until it works. "
        "I led a team of twelve through three failed prototypes before the fourth.",
        ("harvard", 2),
    ),
    (
        "Serving the community",
        "Every Saturday the food bank needs more hands than it has. "
        "Packing those boxes showed me how much planning sits behind one meal.",
        ("yale", 7),
    ),
)
"""Title, body and the (school slug, prompt position) the essay answers."""


async def _link(
    s: AsyncSession, student: UUID, slug: str, position: int
) -> tuple[UUID | None, tuple[PromptTarget, ...]]:
    """The student's list entry and the latest-cycle prompt of a school."""
    inst = await s.scalar(select(InstitutionRow.id).where(InstitutionRow.slug == slug))
    if inst is None:
        return None, ()
    entry = await s.scalar(
        select(ListEntryRow.id).where(
            ListEntryRow.student_id == student, ListEntryRow.institution_id == inst
        )
    )
    row = await s.scalar(
        select(SuppPromptRow)
        .where(SuppPromptRow.institution_id == inst, SuppPromptRow.position == position)
        .order_by(SuppPromptRow.cycle.desc())
        .limit(1)
    )
    if row is None:
        return entry, ()
    return entry, (PromptTarget(inst, position, row.prompt, row.word_limit),)


async def _essays(container: Container, s: AsyncSession, student: UUID) -> None:
    """Demo essays with fixed ids, linked to a listed school's prompt.

    A row whose text no longer opens is recreated; an unlinked one gets its link.
    """
    repo = SqlEssayRepository(s, essay_cipher(container.settings))
    for n, (title, body, (slug, position)) in enumerate(ESSAY_TEXTS):
        essay_id = uuid5(_NS, f"essay:{n}")
        entry, targets = await _link(s, student, slug, position)
        if await s.get(EssayRow, essay_id) is not None:
            try:
                essay = await repo.get(essay_id)
            except (EssayKeyUnavailableError, ValueError):
                await repo.delete(essay_id)
                print(f"recreating demo essay {n}: its key is gone")
            else:
                if essay is not None and not essay.targets and targets:
                    await repo.update(
                        replace(essay, list_entry_id=entry, targets=targets)
                    )
                continue
        await repo.add(
            Essay(
                id=essay_id,
                student_id=student,
                title=title,
                body=body,
                list_entry_id=entry,
                targets=targets,
            )
        )


async def _repair(container: Container, user_id: UUID, roles: set[Role]) -> None:
    """Bring an account created by an earlier run back to the demo state."""
    auth = container.identity.auth
    async with auth.uow_factory() as uow:
        user = await uow.users.get(user_id)
        if user is None:
            return
        changed = False
        if not await auth.hasher.verify(user.password_hash, PASSWORD):
            user.password_hash = await auth.hasher.hash(PASSWORD)
            changed = True
        if user.status != UserStatus.ACTIVE:
            user.status = UserStatus.ACTIVE
            changed = True
        if user.roles != roles:
            user.roles = set(roles)
            changed = True
        if changed:
            await uow.users.save(user)
            await uow.commit()


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
        await _repair(container, ids[key], set(roles))
    now = container.clock.now()
    student = ids["student"]
    async with container.sessionmaker() as s:
        await load_catalog(s, now)
        for owner in (student, ids["undecided"]):
            if await s.get(EntitlementRow, owner) is None:
                s.add(EntitlementRow(user_id=owner, kind="school_student"))
        role_ids = {
            r.key: r.id for r in (await s.scalars(select(StaffRoleRow))).all() if r.key
        }
        await _assign(s, ids, role_ids)
        await _items(s, student)
        await _transcript(s, student)
        await _checklist(s, student)
        await _essays(container, s, student)
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
    out(
        "Admission demo accounts (dev only, password sign-in via iht.id;"
        " the password is PASSWORD in scripts/seed_admission_demo.py):"
    )
    for key, login, *_ in ACCOUNTS:
        out(f"  {key:<20} {login}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
