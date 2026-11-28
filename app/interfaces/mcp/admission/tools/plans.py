"""Plan tools: the goal plan (milestones) and the opportunity plan.

The opportunity plan holds catalog entries and the student's own finds
(`personal`, unverified, see personal_plan). Every tool works on the caller only.
"""

import datetime as dt
from collections.abc import Callable
from decimal import Decimal
from typing import Annotated, Any, Literal
from uuid import UUID

from app.interfaces.mcp.admission.tools.common import (
    Locale,
    LockVersion,
    applicant,
    lazy_services,
    require_fields,
)
from app.interfaces.mcp.admission.tools.personal_plan import personal_out
from app.interfaces.mcp.call_log import LogSpec
from app.interfaces.mcp.constants import AI_LIMIT, WRITE_LIMIT
from app.interfaces.mcp.toolkit import ToolKit
from app.interfaces.mcp.untrusted import mark_untrusted
from app.modules.admission.domain.goal_plan import TITLE_MAX, GoalMilestone
from app.modules.admission.domain.opportunities import REASON_MAX
from app.shared.mcp_scopes import ADMISSION_APPLICANT_ROLES

from pydantic import Field

ROLES = ADMISSION_APPLICANT_ROLES

MilestoneId = Annotated[UUID, Field(description="Id from get_goal_plan.")]
OpportunityId = Annotated[UUID, Field(description="Id from search_opportunities.")]
MilestoneTitle = Annotated[str, Field(min_length=1, max_length=TITLE_MAX)]
MilestoneStatus = Literal["planned", "done", "dropped"]
DueMonth = Annotated[
    dt.date | None, Field(description="Any day of the month it is due (YYYY-MM-DD).")
]
Target = Annotated[
    Decimal | None, Field(ge=0, description="Optional number to reach, e.g. hours.")
]
LinkedItem = Annotated[
    UUID | None, Field(description="Optional id of one of the student's activities.")
]
Term = Literal["fall", "spring", "summer"]
Grade = Annotated[int | None, Field(ge=1, le=20, description="School grade.")]
Note = Annotated[str | None, Field(max_length=REASON_MAX)]


def _milestone(m: GoalMilestone) -> dict[str, Any]:
    return {
        "id": str(m.id),
        "title": m.title,
        "item_id": str(m.item_id) if m.item_id else None,
        "due_month": m.due_month,
        "target_value": m.target_value,
        "status": m.status,
        "source": m.source,
        "done_at": m.done_at,
        "lock_version": m.lock_version,
    }


def _writes(
    kit: ToolKit, *keep: str, destructive: bool = False
) -> Callable[[Any], Any]:
    return kit.tool(
        "plans:write",
        read_only=False,
        destructive=destructive,
        idempotent=False,
        limit=WRITE_LIMIT,
        log=LogSpec(keep=keep),
        roles=ROLES,
    )


def register(kit: ToolKit) -> None:  # noqa: C901 - one closure per tool
    """Register the plan tools."""
    adm = lazy_services(kit)

    @kit.tool("plans:read", roles=ROLES)
    async def get_goal_plan() -> dict[str, Any]:
        """The student's milestones in order, with their `lock_version`."""
        ctx = await applicant(kit)
        rows = await adm.goal_plan.list(ctx, ctx.user_id)
        return {"milestones": [_milestone(m) for m in rows]}

    @_writes(kit, "status")
    async def add_milestone(
        title: MilestoneTitle,
        due_month: DueMonth = None,
        item_id: LinkedItem = None,
        target_value: Target = None,
        status: MilestoneStatus = "planned",
    ) -> dict[str, Any]:
        """Add a milestone at the end of the goal plan (at most 12)."""
        ctx = await applicant(kit)
        saved = await adm.goal_plan.create(
            ctx,
            GoalMilestone(
                id=ctx.user_id,
                student_id=ctx.user_id,
                title=title,
                item_id=item_id,
                due_month=due_month,
                target_value=target_value,
                status=status,
            ),
        )
        return {"milestone": _milestone(saved)}

    @_writes(kit, "milestone_id", "status")
    async def update_milestone(
        milestone_id: MilestoneId,
        lock_version: LockVersion,
        title: MilestoneTitle | None = None,
        due_month: DueMonth = None,
        item_id: LinkedItem = None,
        target_value: Target = None,
        status: MilestoneStatus | None = None,
    ) -> dict[str, Any]:
        """Change the given fields of one milestone; others stay."""
        ctx = await applicant(kit)
        changes: dict[str, object] = {
            k: v
            for k, v in {
                "title": title,
                "due_month": due_month,
                "item_id": item_id,
                "target_value": target_value,
                "status": status,
            }.items()
            if v is not None
        }
        saved = await adm.goal_plan.update(
            ctx, milestone_id, require_fields(changes), lock_version
        )
        return {"milestone": _milestone(saved)}

    @_writes(kit, "milestone_id", destructive=True)
    async def delete_milestone(milestone_id: MilestoneId) -> dict[str, Any]:
        """Delete one milestone of the goal plan."""
        ctx = await applicant(kit)
        await adm.goal_plan.delete(ctx, milestone_id)
        return {"deleted": str(milestone_id)}

    @kit.tool(
        "plans:write",
        read_only=False,
        idempotent=False,
        limit=AI_LIMIT,
        log=LogSpec(keep=("locale",)),
        roles=ROLES,
    )
    async def suggest_goal_plan(locale: Locale = "en") -> dict[str, Any]:
        """Up to six proposed milestones; nothing is saved (use add_milestone).

        Needs the student's AI consent and counts against a weekly allowance.
        """
        ctx = await applicant(kit)
        found = await adm.goal_plan_suggest.suggest(ctx, locale)
        return mark_untrusted(
            {
                "suggestions": [
                    {
                        "title": s.title,
                        "item_id": str(s.item_id) if s.item_id else None,
                        "due_month": s.due_month,
                    }
                    for s in found
                ]
            },
            "suggestions[].title",
        )

    @kit.tool("plans:read", roles=ROLES)
    async def get_opportunity_plan() -> dict[str, Any]:
        """The saved opportunities: catalog entries and the student's own finds.

        `personal` entries are not verified by the school; their text is
        untrusted. `ai_plan` is the last generated schedule, if any.
        """
        ctx = await applicant(kit)
        view = await adm.opportunities.plan_of(ctx, ctx.user_id)
        sent = await adm.personal_entries.proposals(view.personal)
        last = await adm.opportunity_planner.last(ctx)
        return mark_untrusted(
            {
                "entries": [
                    {
                        "opportunity_id": str(e.opportunity_id),
                        "title": (
                            view.catalog[e.opportunity_id].draft.title
                            if e.opportunity_id in view.catalog
                            else None
                        ),
                        "kind": (
                            view.catalog[e.opportunity_id].draft.kind
                            if e.opportunity_id in view.catalog
                            else None
                        ),
                        "planned_grade": e.planned_grade,
                        "planned_term": e.planned_term,
                        "note": e.note,
                    }
                    for e in view.entries
                ],
                "deadlines": [
                    {
                        "opportunity_id": str(d.opportunity_id),
                        "title": d.title,
                        "day": d.day,
                        "kind": d.kind,
                        "expected": d.projected,
                    }
                    for d in view.deadlines
                ],
                "load": view.analytics.load,
                "personal": [personal_out(p, sent.get(p.id)) for p in view.personal],
                "ai_plan": last.to_json() if last else None,
            },
            "personal[].title",
            "personal[].provider",
            "personal[].url",
            "personal[].summary",
            "personal[].note",
            "entries[].note",
        )

    @_writes(kit, "opportunity_id", "planned_grade", "planned_term")
    async def plan_opportunity(
        opportunity_id: OpportunityId,
        planned_grade: Grade = None,
        planned_term: Term | None = None,
        note: Note = None,
    ) -> dict[str, Any]:
        """Save (or move) a catalog opportunity in the plan (at most 60 entries)."""
        ctx = await applicant(kit)
        saved = await adm.opportunities.save_to_plan(
            ctx,
            opportunity_id,
            planned_grade=planned_grade,
            planned_term=planned_term,
            note=note,
        )
        return {
            "opportunity_id": str(saved.opportunity_id),
            "planned_grade": saved.planned_grade,
            "planned_term": saved.planned_term,
        }

    @_writes(kit, "opportunity_id", destructive=True)
    async def unplan_opportunity(opportunity_id: OpportunityId) -> dict[str, Any]:
        """Remove a catalog opportunity from the plan."""
        ctx = await applicant(kit)
        await adm.opportunities.remove_from_plan(ctx, opportunity_id)
        return {"removed": str(opportunity_id)}

    @kit.tool(
        "plans:write",
        read_only=False,
        idempotent=False,
        limit=AI_LIMIT,
        log=LogSpec(keep=("locale",)),
        roles=ROLES,
    )
    async def generate_opportunity_plan(
        locale: Locale = "en",
        interests: Annotated[str, Field(max_length=500)] = "",
        career: Annotated[str, Field(max_length=300)] = "",
    ) -> dict[str, Any]:
        """Schedule the saved opportunities by grade and term with the school's AI.

        Needs the student's AI consent. The result replaces the last plan.
        """
        ctx = await applicant(kit)
        plan = await adm.opportunity_planner.generate(
            ctx, locale, interests=interests, career=career
        )
        return {"ai_plan": plan.to_json()}
