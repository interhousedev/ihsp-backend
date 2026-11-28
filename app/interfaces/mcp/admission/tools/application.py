"""Application tools: the caller's profile, activities, test scores, tasks, readiness.

Every tool works on the calling student only: the student id comes from the token,
and an id of another student's activity or score answers the same not-found as a
random id.
"""

import datetime as dt
from collections.abc import Callable
from typing import Annotated, Any, Literal
from uuid import UUID

from app.interfaces.mcp.admission.tools.common import (
    ItemId,
    Locale,
    LockVersion,
    applicant,
    lazy_services,
    require_fields,
    services,
)
from app.interfaces.mcp.call_log import LogSpec
from app.interfaces.mcp.constants import WRITE_LIMIT
from app.interfaces.mcp.errors import McpNotFoundError
from app.interfaces.mcp.toolkit import ToolKit
from app.modules.admission.application.actor import AdmissionContext
from app.modules.admission.domain.items import Item
from app.modules.admission.domain.test_scores import (
    LABEL_MAX,
    LEVEL_MAX,
    NOTE_MAX,
    URL_MAX,
    EntryStatus,
    ScoreEntryDraft,
)
from app.shared.mcp_scopes import ADMISSION_APPLICANT_ROLES

from pydantic import Field

ROLES = ADMISSION_APPLICANT_ROLES
TITLE_MAX = 60
ORGANIZATION_MAX = 110
DESCRIPTION_MAX = 600

ItemKind = Literal["activity", "honor"]
ItemStatus = Literal["draft", "ready"]
Grade = Literal[9, 10, 11, 12, 13]
Timing = Literal["school_year", "school_break", "all_year"]
ScoreStatus = EntryStatus
TaskStatus = Literal["planned", "in_progress", "in_review", "blocked", "done"]
ScoreValue = int | float | str
ScoreId = Annotated[UUID, Field(description="Id of one of the student's test scores.")]
Title = Annotated[
    str,
    Field(max_length=TITLE_MAX, description="Position or honor title (60 chars)."),
]
Organization = Annotated[
    str, Field(max_length=ORGANIZATION_MAX, description="Organization (110 chars).")
]
Description = Annotated[
    str, Field(max_length=DESCRIPTION_MAX, description="What was done (600 chars).")
]
Grades = Annotated[
    list[Grade], Field(max_length=5, description="School grades of participation.")
]
Timings = Annotated[
    list[Timing], Field(max_length=3, description="When the activity takes place.")
]
Hours = Annotated[int, Field(ge=0, le=168, description="Hours per week.")]
Weeks = Annotated[int, Field(ge=0, le=52, description="Weeks per year.")]
Category = Annotated[str, Field(max_length=40, description="Common App category.")]
Level = Annotated[
    str, Field(max_length=16, description="Honors only: recognition level.")
]


async def _own_item(
    kit: ToolKit, ctx: AdmissionContext, item_id: UUID
) -> Any:  # noqa: ANN401 - ItemView
    """The caller's item view; another student's id is not found."""
    views = await services(kit).items.list_items(ctx, ctx.user_id)
    for view in views:
        if view.item.id == item_id:
            return view
    raise McpNotFoundError()


async def _own_score(kit: ToolKit, ctx: AdmissionContext, entry_id: UUID) -> None:
    overview = await services(kit).test_scores.overview(ctx)
    if not any(e.id == entry_id for e in overview.entries):
        raise McpNotFoundError()


TestId = Annotated[UUID, Field(description="Test id from the score catalog.")]
Label = Annotated[str, Field(max_length=LABEL_MAX)]
ScoreLevel = Annotated[str, Field(max_length=LEVEL_MAX)]
Sections = Annotated[
    dict[str, ScoreValue], Field(description="Section scores by section key.")
]
VerifyUrl = Annotated[str, Field(max_length=URL_MAX)]
SendNote = Annotated[str, Field(max_length=NOTE_MAX)]


def _score_draft(
    test_id: UUID,
    status: EntryStatus,
    test_date: dt.date | None,
    registration_deadline: dt.date | None,
    label: str | None,
    level: str | None,
    sections: dict[str, ScoreValue] | None,
    total: ScoreValue | None,
    verification_url: str | None,
    send_note: str | None,
) -> ScoreEntryDraft:
    return ScoreEntryDraft(
        test_id=test_id,
        status=status,
        test_date=test_date,
        registration_deadline=registration_deadline,
        label=label,
        level=level,
        sections=dict(sections or {}),
        total=total,
        certificate_document_id=None,
        verification_url=verification_url,
        send_note=send_note,
        is_official=False,
    )


def _writes(kit: ToolKit, *keep: str) -> Callable[[Any], Any]:
    """Decorator of a non-destructive application write tool."""
    return kit.tool(
        "application:write",
        read_only=False,
        idempotent=False,
        limit=WRITE_LIMIT,
        log=LogSpec(keep=keep),
        roles=ROLES,
    )


def register(kit: ToolKit) -> None:  # noqa: C901 - one closure per tool
    """Register the application tools."""
    adm = lazy_services(kit)

    @kit.tool("application:read", roles=ROLES)
    async def get_application() -> dict[str, Any]:
        """The whole application in one read.

        Profile, tasks, activities, test scores, university list, deadlines and
        courses. Next: get_readiness for what is still missing.
        """
        ctx = await applicant(kit)
        data, me = adm.application_data, ctx.user_id
        return {
            "profile": await data.profile(me),
            "tasks": await data.tasks(me),
            "activities": await data.items(me),
            "test_scores": await data.test_scores(me),
            "universities": await data.universities(me),
            "deadlines": await data.deadlines(me),
            "courses": await data.courses(me),
        }

    @kit.tool("application:read", roles=ROLES)
    async def get_today(locale: Locale = "en") -> dict[str, Any]:
        """Today's view: season, next steps, streak, readiness, nearest deadlines."""
        ctx = await applicant(kit)
        return {"today": await adm.today.get(ctx, locale)}

    @kit.tool("application:read", roles=ROLES)
    async def get_profile() -> dict[str, Any]:
        """The profile answers with their `lock_version` (needed by update_profile)."""
        ctx = await applicant(kit)
        return {"profile": await adm.profile.get(ctx, ctx.user_id)}

    @_writes(kit)
    async def update_profile(
        answers: Annotated[
            dict[str, Any],
            Field(description="Answers to change, keyed by question id."),
        ],
        lock_version: Annotated[
            int | None,
            Field(description="From get_profile; null only for a new profile."),
        ],
    ) -> dict[str, Any]:
        """Save one or more profile answers; a stale `lock_version` is refused."""
        ctx = await applicant(kit)
        require_fields(answers)
        return {"profile": await adm.profile.save(ctx, answers, lock_version)}

    @kit.tool("application:read", roles=ROLES)
    async def list_activities() -> dict[str, Any]:
        """The student's activities and honors, with metrics and latest reviews."""
        ctx = await applicant(kit)
        return {"items": await adm.items.list_items(ctx, ctx.user_id)}

    @kit.tool("application:read", roles=ROLES)
    async def list_honor_suggestions(locale: Locale = "en") -> dict[str, Any]:
        """Platform certificates of the student that could become honors."""
        ctx = await applicant(kit)
        found = await adm.honor_suggestions.suggestions(ctx, locale)
        return {"suggested": found.suggested, "available": found.available}

    @kit.tool("application:read", roles=ROLES)
    async def list_certificate_proofs(item_id: ItemId) -> dict[str, Any]:
        """The proofs (links, files, texts) attached to one activity or honor."""
        ctx = await applicant(kit)
        await _own_item(kit, ctx, item_id)
        return {"items": await adm.proofs.list(ctx, item_id)}

    @_writes(kit, "kind", "status")
    async def add_activity(
        kind: ItemKind,
        title: Title,
        organization: Organization = "",
        description: Description = "",
        category: Category | None = None,
        grades: Grades | None = None,
        hours_per_week: Hours | None = None,
        weeks_per_year: Weeks | None = None,
        status: ItemStatus = "draft",
        timing: Timings | None = None,
        intend_in_college: bool | None = None,
        level: Level | None = None,
        certificate_entry_id: Annotated[
            UUID | None,
            Field(description="Honors only: id from list_honor_suggestions."),
        ] = None,
    ) -> dict[str, Any]:
        """Add an activity or honor at the end of its list."""
        ctx = await applicant(kit)
        item = Item(
            id=ctx.user_id,
            student_id=ctx.user_id,
            kind=kind,
            title=title,
            organization=organization,
            description=description,
            category=category,
            grades=tuple(grades or ()),
            hours_per_week=hours_per_week,
            weeks_per_year=weeks_per_year,
            status=status,
            timing=tuple(timing or ()),
            intend_in_college=intend_in_college,
            level=level,
            certificate_entry_id=certificate_entry_id,
        )
        return {"item": await adm.items.create(ctx, item, [])}

    @_writes(kit, "item_id")
    async def update_activity(
        item_id: ItemId,
        lock_version: LockVersion,
        title: Title | None = None,
        organization: Organization | None = None,
        description: Description | None = None,
        category: Category | None = None,
        grades: Grades | None = None,
        hours_per_week: Hours | None = None,
        weeks_per_year: Weeks | None = None,
        status: ItemStatus | None = None,
        timing: Timings | None = None,
        intend_in_college: bool | None = None,
        level: Level | None = None,
    ) -> dict[str, Any]:
        """Change fields of one activity or honor; omitted fields stay."""
        ctx = await applicant(kit)
        await _own_item(kit, ctx, item_id)
        given = {
            "title": title,
            "organization": organization,
            "description": description,
            "category": category,
            "grades": tuple(grades) if grades is not None else None,
            "hours_per_week": hours_per_week,
            "weeks_per_year": weeks_per_year,
            "status": status,
            "timing": tuple(timing) if timing is not None else None,
            "intend_in_college": intend_in_college,
            "level": level,
        }
        changes = require_fields({k: v for k, v in given.items() if v is not None})
        await adm.items.update(ctx, item_id, changes, lock_version)
        return {"item": await _own_item(kit, ctx, item_id)}

    @kit.tool(
        "application:write",
        read_only=False,
        destructive=True,
        idempotent=True,
        limit=WRITE_LIMIT,
        log=LogSpec(keep=("item_id",)),
        roles=ROLES,
    )
    async def delete_activity(item_id: ItemId) -> dict[str, Any]:
        """Delete one activity or honor with its metrics, interview and reviews."""
        ctx = await applicant(kit)
        await _own_item(kit, ctx, item_id)
        await adm.items.delete(ctx, item_id)
        return {"deleted": str(item_id)}

    @kit.tool("application:read", roles=ROLES)
    async def list_test_scores() -> dict[str, Any]:
        """Test entries with the best result and superscore of each test."""
        ctx = await applicant(kit)
        return {"overview": await adm.test_scores.overview(ctx)}

    @_writes(kit, "test_id", "status")
    async def add_test_score(
        test_id: TestId,
        status: ScoreStatus,
        test_date: dt.date | None = None,
        registration_deadline: dt.date | None = None,
        label: Label | None = None,
        level: ScoreLevel | None = None,
        sections: Sections | None = None,
        total: ScoreValue | None = None,
        verification_url: VerifyUrl | None = None,
        send_note: SendNote | None = None,
    ) -> dict[str, Any]:
        """Add a planned, registered or taken test sitting (at most 100)."""
        ctx = await applicant(kit)
        draft = _score_draft(
            test_id,
            status,
            test_date,
            registration_deadline,
            label,
            level,
            sections,
            total,
            verification_url,
            send_note,
        )
        return {"entry": await adm.test_scores.create(ctx, draft)}

    @_writes(kit, "entry_id", "status")
    async def update_test_score(
        entry_id: ScoreId,
        test_id: TestId,
        status: ScoreStatus,
        test_date: dt.date | None = None,
        registration_deadline: dt.date | None = None,
        label: Label | None = None,
        level: ScoreLevel | None = None,
        sections: Sections | None = None,
        total: ScoreValue | None = None,
        verification_url: VerifyUrl | None = None,
        send_note: SendNote | None = None,
    ) -> dict[str, Any]:
        """Replace one test entry (all fields); this clears its verification."""
        ctx = await applicant(kit)
        await _own_score(kit, ctx, entry_id)
        draft = _score_draft(
            test_id,
            status,
            test_date,
            registration_deadline,
            label,
            level,
            sections,
            total,
            verification_url,
            send_note,
        )
        return {"entry": await adm.test_scores.update(ctx, entry_id, draft)}

    @kit.tool(
        "application:write",
        read_only=False,
        destructive=True,
        idempotent=True,
        limit=WRITE_LIMIT,
        log=LogSpec(keep=("entry_id",)),
        roles=ROLES,
    )
    async def delete_test_score(entry_id: ScoreId) -> dict[str, Any]:
        """Remove one test entry."""
        ctx = await applicant(kit)
        await _own_score(kit, ctx, entry_id)
        await adm.test_scores.delete(ctx, entry_id)
        return {"deleted": str(entry_id)}

    @kit.tool("application:read", roles=ROLES)
    async def list_tasks(status: TaskStatus | None = None) -> dict[str, Any]:
        """The student's tasks, optionally of one status."""
        ctx = await applicant(kit)
        return {"items": await adm.tasks.list_for(ctx, ctx.user_id, status=status)}

    @kit.tool("application:read", roles=ROLES)
    async def get_readiness() -> dict[str, Any]:
        """The readiness percentage and what each component still misses."""
        ctx = await applicant(kit)
        return {"readiness": await adm.readiness.get(ctx)}

    @kit.tool("application:read", roles=ROLES)
    async def list_checklist() -> dict[str, Any]:
        """The document checklist; per-university items name their university."""
        ctx = await applicant(kit)
        rows = await adm.documents.checklist(ctx)
        return {"items": [{"item": item, "university": b} for item, b in rows]}

    @kit.tool("application:read", roles=ROLES)
    async def get_school_grades() -> dict[str, Any]:
        """The school grades the admission programme serves."""
        await applicant(kit)
        return {"grades": list(await adm.school_grades.get())}

    @kit.tool("application:read", roles=ROLES)
    async def get_my_university_list(
        cycle: Annotated[
            str | None,
            Field(pattern=r"^\d{4}-\d{2}$", description="One cycle, e.g. 2026-27."),
        ] = None,
    ) -> dict[str, Any]:
        """The student's university list with rounds, deadlines and status."""
        ctx = await applicant(kit)
        return {"items": await adm.chooser.view(ctx, ctx.user_id, cycle)}
