"""What staff tools may hand to an external AI client (decision: AI consent only).

A student's personal data leaves through a staff tool only when the student holds
the AI purpose consent; otherwise the student is shown by name with
`withheld: "ai-consent"`. Recommendation letters, bank documents and confidential
files are never served; essays only as the versions the student shared.
"""

from collections.abc import Iterable
from typing import Any, Final
from uuid import UUID

from app.interfaces.mcp.admission.tools.common import services
from app.interfaces.mcp.guard import current_actor
from app.interfaces.mcp.toolkit import ToolKit
from app.modules.admission.application.actor import AdmissionContext
from app.modules.admission.application.staff import CaseloadFilters
from app.modules.admission.domain.errors import (
    AdmissionForbiddenError,
    AdmissionNotFoundError,
)
from app.modules.admission.ports.consent import AI

WITHHELD_AI: Final = "ai-consent"
BLOCKED_KINDS: Final = frozenset({"rec", "bank"})
"""Document kinds no MCP tool lists or reads (letters, bank statements)."""


async def staff_context(kit: ToolKit) -> AdmissionContext:
    """The admission context of the calling staff member; others are refused."""
    ctx: AdmissionContext = await services(kit).actor.execute(current_actor())
    if not ctx.admission.is_staff:
        raise AdmissionForbiddenError(params={"permission": "staff"})
    return ctx


async def ai_holders(kit: ToolKit, student_ids: Iterable[UUID]) -> frozenset[UUID]:
    """The students among `student_ids` who hold the AI purpose consent."""
    ids = list(dict.fromkeys(student_ids))
    if not ids:
        return frozenset()
    granted = await services(kit).consents.granted(ids)
    return frozenset(u for u, purposes in granted.items() if AI in purposes)


async def student_name(
    kit: ToolKit, ctx: AdmissionContext, student_id: UUID
) -> str | None:
    """The display name of a student in the caller's caseload, if known."""
    try:
        items = await services(kit).staff.caseload(ctx, CaseloadFilters())
    except (AdmissionForbiddenError, AdmissionNotFoundError):
        return None
    for item in items:
        if item.row.student_id == student_id:
            return str(item.student_name) if item.student_name else None
    return None


def withheld(student_id: UUID, name: str | None) -> dict[str, Any]:
    """The answer for a student without the AI consent: the name, nothing else."""
    return {"student_id": str(student_id), "name": name, "withheld": WITHHELD_AI}


async def shareable(
    kit: ToolKit, ctx: AdmissionContext, student_id: UUID
) -> dict[str, Any] | None:
    """None when the student's data may be returned, else the `withheld` answer."""
    if student_id in await ai_holders(kit, [student_id]):
        return None
    return withheld(student_id, await student_name(kit, ctx, student_id))


def servable_document(view: Any) -> bool:  # noqa: ANN401 - DocumentView
    """Whether a document may reach an AI client: no letters, bank, confidential."""
    doc = view.doc
    return doc.kind not in BLOCKED_KINDS and doc.visibility != "confidential"
