"""Personal plan tools: the student's own finds that are not in the catalog.

An entry written here is shown to the student as "not verified by the school"
and "added through an AI assistant". The link is checked as text and never
fetched. Titles, notes and URLs never reach the call log.
"""

import datetime as dt
from typing import Annotated, Any
from uuid import UUID

from app.interfaces.mcp.admission.tools.common import (
    LockVersion,
    applicant,
    lazy_services,
)
from app.interfaces.mcp.call_log import LogSpec
from app.interfaces.mcp.constants import WRITE_LIMIT
from app.interfaces.mcp.toolkit import ToolKit
from app.interfaces.mcp.untrusted import mark_untrusted
from app.modules.admission.application.personal_entries import Proposal
from app.modules.admission.domain.opportunities import (
    REASON_MAX,
    TITLE_MAX,
    OpportunityKind,
)
from app.modules.admission.domain.personal_entries import (
    URL_MAX,
    PersonalDraft,
    PersonalEntry,
)
from app.shared.mcp_scopes import ADMISSION_APPLICANT_ROLES

from pydantic import Field

ROLES = ADMISSION_APPLICANT_ROLES
PROVIDER_MAX = 300
SUMMARY_MAX = 2000
UNTRUSTED = (
    "entry.title",
    "entry.provider",
    "entry.url",
    "entry.summary",
    "entry.note",
)

EntryId = Annotated[UUID, Field(description="Id of one of the student's own finds.")]
Title = Annotated[
    str, Field(min_length=1, max_length=TITLE_MAX, description="Name of the program.")
]
Provider = Annotated[
    str | None, Field(max_length=PROVIDER_MAX, description="Organiser.")
]
Url = Annotated[
    str | None,
    Field(max_length=URL_MAX, description="https link to the organiser's page."),
]
Summary = Annotated[
    str | None, Field(max_length=SUMMARY_MAX, description="What it is, briefly.")
]
Day = Annotated[
    dt.date | None, Field(description="Date from the organiser's page (YYYY-MM-DD).")
]
PlannedGrade = Annotated[
    int | None, Field(ge=1, le=20, description="School grade to do it in.")
]
PlannedTerm = Annotated[
    str | None, Field(max_length=8, description="fall, spring or summer.")
]
Note = Annotated[
    str | None, Field(max_length=REASON_MAX, description="The student's note.")
]


def personal_out(entry: PersonalEntry, proposal: Proposal | None) -> dict[str, Any]:
    """One find as the tools show it (fields are untrusted text)."""
    return {
        "id": str(entry.id),
        "kind": entry.kind,
        "title": entry.title,
        "provider": entry.provider,
        "url": entry.url,
        "summary": entry.summary,
        "registration_deadline": entry.registration_deadline,
        "starts_on": entry.starts_on,
        "ends_on": entry.ends_on,
        "planned_grade": entry.planned_grade,
        "planned_term": entry.planned_term,
        "note": entry.note,
        "origin": entry.origin,
        "verified": False,
        "proposal": (
            {"submission_id": str(proposal.submission_id), "status": proposal.status}
            if proposal
            else None
        ),
        "lock_version": entry.lock_version,
        "created_at": entry.created_at,
    }


def register(kit: ToolKit) -> None:
    """Register the personal plan tools."""
    adm = lazy_services(kit)

    @kit.tool(
        "plans:write",
        read_only=False,
        idempotent=True,
        limit=WRITE_LIMIT,
        log=LogSpec(keep=("kind",)),
        roles=ROLES,
    )
    async def add_external_opportunity(
        kind: OpportunityKind,
        title: Title,
        provider: Provider = None,
        url: Url = None,
        summary: Summary = None,
        registration_deadline: Day = None,
        starts_on: Day = None,
        ends_on: Day = None,
        planned_grade: PlannedGrade = None,
        planned_term: PlannedTerm = None,
        note: Note = None,
        propose_to_catalog: Annotated[
            bool,
            Field(description="Also send it to the school's catalog moderation."),
        ] = False,
    ) -> dict[str, Any]:
        """Save a program found outside the catalog to the student's plan.

        Call search_opportunities first: a catalog entry is planned with
        plan_opportunity. When this find matches a published catalog entry, that
        entry is planned instead and `planned_opportunity_id` is returned with
        reason `already_in_catalog`. Dates must come from the organiser's page.
        The student sees the entry as not verified by the school; at most 20
        additions a day. The same find twice answers `plan-duplicate`.
        """
        ctx = await applicant(kit)
        added = await adm.personal_entries.add(
            ctx,
            PersonalDraft(
                kind=kind,
                title=title,
                provider=provider,
                url=url,
                summary=summary,
                registration_deadline=registration_deadline,
                starts_on=starts_on,
                ends_on=ends_on,
                planned_grade=planned_grade,
                planned_term=planned_term,
                note=note,
            ),
            origin="mcp",
            propose=propose_to_catalog,
        )
        if added.entry is None:
            return {
                "planned_opportunity_id": str(added.planned_opportunity_id),
                "reason": "already_in_catalog",
            }
        sent = await adm.personal_entries.proposals([added.entry])
        return mark_untrusted(
            {"entry": personal_out(added.entry, sent.get(added.entry.id))},
            *UNTRUSTED,
        )

    @kit.tool(
        "plans:write",
        read_only=False,
        idempotent=False,
        limit=WRITE_LIMIT,
        log=LogSpec(keep=("entry_id", "kind")),
        roles=ROLES,
    )
    async def update_external_opportunity(
        entry_id: EntryId,
        lock_version: LockVersion,
        kind: OpportunityKind,
        title: Title,
        provider: Provider = None,
        url: Url = None,
        summary: Summary = None,
        registration_deadline: Day = None,
        starts_on: Day = None,
        ends_on: Day = None,
        planned_grade: PlannedGrade = None,
        planned_term: PlannedTerm = None,
        note: Note = None,
    ) -> dict[str, Any]:
        """Replace all fields of one of the student's own finds.

        Pass every field to keep (an omitted one is emptied). The `lock_version`
        comes from get_opportunity_plan; a stale one is refused.
        """
        ctx = await applicant(kit)
        saved = await adm.personal_entries.update(
            ctx,
            entry_id,
            PersonalDraft(
                kind=kind,
                title=title,
                provider=provider,
                url=url,
                summary=summary,
                registration_deadline=registration_deadline,
                starts_on=starts_on,
                ends_on=ends_on,
                planned_grade=planned_grade,
                planned_term=planned_term,
                note=note,
            ),
            lock_version=lock_version,
        )
        sent = await adm.personal_entries.proposals([saved])
        return mark_untrusted(
            {"entry": personal_out(saved, sent.get(saved.id))}, *UNTRUSTED
        )

    @kit.tool(
        "plans:write",
        read_only=False,
        destructive=True,
        idempotent=False,
        limit=WRITE_LIMIT,
        log=LogSpec(keep=("entry_id",)),
        roles=ROLES,
    )
    async def remove_external_opportunity(entry_id: EntryId) -> dict[str, Any]:
        """Remove one of the student's own finds from the plan.

        A catalog proposal already sent for it stays in moderation.
        """
        ctx = await applicant(kit)
        await adm.personal_entries.delete(ctx, entry_id)
        return {"removed": str(entry_id)}
