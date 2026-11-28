"""Caseload tools: the students the caller reaches, their deadlines, document queue."""

from typing import Annotated, Any, Literal
from uuid import UUID

from app.interfaces.mcp.admission.sharing import (
    ai_holders,
    servable_document,
    staff_context,
    withheld,
)
from app.interfaces.mcp.admission.tools.common import lazy_services
from app.interfaces.mcp.toolkit import ToolKit
from app.modules.admission.application.staff import CaseloadFilters
from app.shared.mcp_scopes import ADMISSION_STAFF_ROLES

from pydantic import Field

ROLES = ADMISSION_STAFF_ROLES
PAGE = 50


def register(kit: ToolKit) -> None:  # noqa: C901 - one closure per tool
    """Register the caseload tools."""
    adm = lazy_services(kit)

    @kit.tool("caseload:read", roles=ROLES)
    async def list_caseload(
        stage: Annotated[str | None, Field(description="Only this stage.")] = None,
        at_risk: Annotated[bool, Field(description="Only students overdue.")] = False,
        query: Annotated[str, Field(max_length=80, description="Name filter.")] = "",
        offset: Annotated[int, Field(ge=0)] = 0,
    ) -> dict[str, Any]:
        """Students assigned to the caller, soonest deadline first (50 per page).

        A student who has not allowed AI use is listed by name only, and only when
        no stage or at_risk filter is given.
        Next: get_student_application, get_student_readiness.
        """
        ctx = await staff_context(kit)
        items = await adm.staff.caseload(
            ctx, CaseloadFilters(stage=stage, risk=at_risk, query=query)
        )
        needle = query.strip().casefold()
        if needle:
            items = [i for i in items if needle in (i.student_name or "").casefold()]
        holders = await ai_holders(kit, (i.row.student_id for i in items))
        if stage is not None or at_risk:
            # Stage and risk are withheld state: a non-consenting student must not
            # appear or disappear by them, so filtered queries skip them entirely.
            items = [i for i in items if i.row.student_id in holders]
        page = items[offset : offset + PAGE]
        rows: list[dict[str, Any]] = []
        for i in page:
            sid = i.row.student_id
            if sid not in holders:
                rows.append(withheld(sid, i.student_name))
                continue
            rows.append(
                {
                    "student_id": str(sid),
                    "name": i.student_name,
                    "group": i.row.group_name,
                    "stage": i.row.stage,
                    "next_due": i.row.next_due,
                    "overdue": i.row.overdue,
                    "open_help": i.row.open_help,
                }
            )
        return {"items": rows, "total": len(items), "offset": offset}

    @kit.tool("caseload:read", roles=ROLES)
    async def list_caseload_deadlines(
        scope: Annotated[
            Literal["mine", "all"],
            Field(description="mine: assigned to the caller; all: everyone reached."),
        ] = "mine",
        locale: Annotated[Literal["uz", "ru", "en"], Field()] = "en",
    ) -> dict[str, Any]:
        """Deadlines and counselor tasks of the caller's students, soonest first."""
        ctx = await staff_context(kit)
        rows = await adm.staff_timeline.get(ctx, scope, locale)
        holders = await ai_holders(kit, (r.student_id for r in rows))
        shown = [r for r in rows if r.student_id in holders]
        hidden = {r.student_id: r.student_name for r in rows} if rows else {}
        return {
            "items": [
                {
                    "student_id": str(r.student_id),
                    "name": r.student_name,
                    "date": r.date,
                    "title": r.title,
                    "kind": r.kind,
                    "by_staff": r.by_staff,
                }
                for r in shown
            ],
            "withheld": [
                withheld(sid, name)
                for sid, name in hidden.items()
                if sid not in holders
            ],
        }

    @kit.tool("caseload:read", roles=ROLES)
    async def list_document_queue(
        review_status: Annotated[
            Literal["none", "accepted", "rejected"] | None,
            Field(description="Only documents in this review status."),
        ] = None,
    ) -> dict[str, Any]:
        """Documents of the caller's students waiting for or past review.

        Recommendation letters and bank documents are never listed. Students
        without AI consent are withheld, and left out when review_status is given.
        Next: read_student_document, review_document.
        """
        ctx = await staff_context(kit)
        views = [
            v
            for v in await adm.documents.staff_queue(ctx, review_status)
            if servable_document(v)
        ]
        holders = await ai_holders(kit, (v.doc.student_id for v in views))
        blocked: list[UUID] = []
        rows: list[dict[str, Any]] = []
        for v in views:
            d = v.doc
            if d.student_id not in holders:
                if review_status is None and d.student_id not in blocked:
                    blocked.append(d.student_id)
                continue
            rows.append(
                {
                    "document_id": str(d.id),
                    "student_id": str(d.student_id),
                    "kind": d.kind,
                    "review_status": d.review_status,
                    "created_at": d.created_at,
                }
            )
        return {
            "items": rows,
            "withheld": [withheld(sid, None) for sid in blocked],
        }
