"""Tools over one student of the caller's caseload.

Every tool starts with the access policy: a student outside the caller's scope and
an id that does not exist both give the same not-found. Personal data follows
only when the student holds the AI consent (see `sharing`).
"""

import datetime as dt
from typing import Annotated, Any, Literal, get_args
from uuid import UUID

from app.interfaces.mcp.admission.sharing import (
    servable_document,
    shareable,
    staff_context,
)
from app.interfaces.mcp.admission.tools.common import lazy_services, services
from app.interfaces.mcp.call_log import LogSpec
from app.interfaces.mcp.constants import WRITE_LIMIT
from app.interfaces.mcp.errors import McpNotFoundError
from app.interfaces.mcp.toolkit import ToolKit
from app.interfaces.mcp.untrusted import clean_text
from app.modules.admission.application.actor import AdmissionContext
from app.modules.admission.domain.errors import (
    AdmissionForbiddenError,
    AdmissionNotFoundError,
)
from app.modules.admission.domain.questions import BY_ID
from app.modules.admission.domain.tasks import (
    DESCRIPTION_MAX,
    TITLE_MAX,
    Task,
    TaskPriority,
)
from app.shared.ids import new_id
from app.shared.mcp_scopes import ADMISSION_STAFF_ROLES

from pydantic import Field
from pydantic_core import to_jsonable_python

ROLES = ADMISSION_STAFF_ROLES
Section = Literal["profile", "activities", "tests", "essays", "tasks"]
CommentTarget = Literal["profile", "item", "list_entry", "words"]
"""Essays are left out: a comment thread there could reach unshared drafts."""
StudentId = Annotated[UUID, Field(description="Id from list_caseload.")]


async def _in_scope(kit: ToolKit, ctx: AdmissionContext, student_id: UUID) -> None:
    """Not-found for a student the caller does not reach (random ids alike)."""
    if not (await services(kit).access.resolve(ctx, student_id)).in_scope:
        raise AdmissionNotFoundError()


async def _section(read: Any) -> Any:  # noqa: ANN401 - a use-case coroutine
    try:
        return to_jsonable_python(await read)
    except AdmissionForbiddenError:
        return {"withheld": "permission"}


def _clean(value: Any) -> Any:  # noqa: ANN401 - plain JSON
    """Clean every string of a student-authored JSON value (untrusted text)."""
    if isinstance(value, str):
        return clean_text(value)
    if isinstance(value, list):
        return [_clean(v) for v in value]
    if isinstance(value, dict):
        return {k: _clean(v) for k, v in value.items()}
    return value


def _finance(question_id: str) -> bool:
    q = BY_ID.get(question_id)
    return q is not None and (
        q.sensitivity == "finance" or q.visible_to == "finance_read"
    )


def _profile(view: Any) -> Any:  # noqa: ANN401 - plain JSON
    """The MCP projection of a profile: never the budget or finance answers.

    Applies whatever the caller's finance permission, so no model sees them.
    """
    if not isinstance(view, dict) or "withheld" in view:
        return view
    out = {k: v for k, v in view.items() if k not in _FINANCE_FIELDS}
    answers = view.get("answers")
    if isinstance(answers, dict):
        out["answers"] = {k: v for k, v in answers.items() if not _finance(k)}
    return out


_FINANCE_FIELDS = frozenset({"family_budget", "budget_shared"})


def register(kit: ToolKit) -> None:  # noqa: C901 - one closure per tool
    """Register the student tools."""
    adm = lazy_services(kit)

    @kit.tool("students:read", roles=ROLES)
    async def get_student_application(
        student_id: StudentId,
        sections: Annotated[
            list[Section] | None,
            Field(description=f"Any of {', '.join(get_args(Section))}; default all."),
        ] = None,
    ) -> dict[str, Any]:
        """A student's application: profile, activities, tests, shared essays, tasks.

        Without the student's AI consent only the name is returned. A section the
        caller's role may not read comes back as withheld; essays only as the
        versions the student shared. Next: get_student_readiness.
        """
        ctx = await staff_context(kit)
        await _in_scope(kit, ctx, student_id)
        if (hidden := await shareable(kit, ctx, student_id)) is not None:
            return hidden
        wanted = list(dict.fromkeys(sections or get_args(Section)))
        out: dict[str, Any] = {"student_id": str(student_id)}
        if "profile" in wanted:
            out["profile"] = _profile(await _section(adm.profile.get(ctx, student_id)))
        if "activities" in wanted:
            out["activities"] = await _section(adm.items.list_items(ctx, student_id))
        if "tests" in wanted:
            out["tests"] = await _section(adm.test_scores.overview(ctx, student_id))
        if "essays" in wanted:
            out["essays"] = await _section(adm.essays.list_shared(ctx, student_id))
        if "tasks" in wanted:
            out["tasks"] = await _section(adm.tasks.list_for(ctx, student_id))
        authored = [s for s in wanted if s != "tests"]
        for name in authored:
            out[name] = _clean(out[name])
        out["untrusted_fields"] = authored
        return out

    @kit.tool("students:read", roles=ROLES)
    async def get_student_readiness(student_id: StudentId) -> dict[str, Any]:
        """The readiness percentage of a student and its components."""
        ctx = await staff_context(kit)
        await _in_scope(kit, ctx, student_id)
        if (hidden := await shareable(kit, ctx, student_id)) is not None:
            return hidden
        return {"readiness": await adm.readiness.get(ctx, student_id)}

    @kit.tool("students:read", roles=ROLES)
    async def list_student_reviews(student_id: StudentId) -> dict[str, Any]:
        """The AI application reviews the student shared with staff (newest first)."""
        ctx = await staff_context(kit)
        await _in_scope(kit, ctx, student_id)
        if (hidden := await shareable(kit, ctx, student_id)) is not None:
            return hidden
        rows = await adm.app_review.staff_list(ctx, student_id)
        return {
            "items": [
                {
                    "id": str(r.id),
                    "version": r.version,
                    "status": r.status,
                    "locale": r.locale,
                    "created_at": r.created_at,
                }
                for r in rows
            ]
        }

    @kit.tool("students:read", roles=ROLES)
    async def get_student_review(
        student_id: StudentId,
        review_id: Annotated[UUID, Field(description="Id from list_student_reviews.")],
    ) -> dict[str, Any]:
        """One shared application review with its sections and report."""
        ctx = await staff_context(kit)
        await _in_scope(kit, ctx, student_id)
        if (hidden := await shareable(kit, ctx, student_id)) is not None:
            return hidden
        return {"review": await adm.app_review.staff_get(ctx, student_id, review_id)}

    @kit.tool("students:read", roles=ROLES)
    async def list_student_documents(student_id: StudentId) -> dict[str, Any]:
        """A student's documents. Recommendation letters and bank files never show."""
        ctx = await staff_context(kit)
        await _in_scope(kit, ctx, student_id)
        if (hidden := await shareable(kit, ctx, student_id)) is not None:
            return hidden
        views = await adm.documents.listing(ctx, student_id)
        return {
            "items": [
                {
                    "document_id": str(v.doc.id),
                    "kind": v.doc.kind,
                    "review_status": v.doc.review_status,
                    "current_version": v.doc.current_version,
                    "can_download": v.can_download,
                }
                for v in views
                if servable_document(v)
            ]
        }

    @kit.tool(
        "students:read",
        read_only=True,
        idempotent=False,
        log=LogSpec(keep=("student_id", "document_id")),
        roles=ROLES,
    )
    async def read_student_document(
        student_id: StudentId,
        document_id: Annotated[UUID, Field(description="From list_student_documents.")],
    ) -> dict[str, Any]:
        """A short-lived download link (5 minutes) for one student document."""
        ctx = await staff_context(kit)
        await _in_scope(kit, ctx, student_id)
        if (hidden := await shareable(kit, ctx, student_id)) is not None:
            return hidden
        views = await adm.documents.listing(ctx, student_id)
        if not any(v.doc.id == document_id and servable_document(v) for v in views):
            raise McpNotFoundError()
        link = await adm.documents.download(ctx, document_id)
        return {"url": link.url, "expires_at": link.expires_at}

    @kit.tool("students:read", roles=ROLES)
    async def list_comments(
        student_id: StudentId,
        target_kind: CommentTarget,
        target_id: Annotated[UUID, Field(description="Id of the commented object.")],
    ) -> dict[str, Any]:
        """Comments on one object of a student's application."""
        ctx = await staff_context(kit)
        await _in_scope(kit, ctx, student_id)
        if (hidden := await shareable(kit, ctx, student_id)) is not None:
            return hidden
        rows = await adm.comments.thread(ctx, student_id, target_kind, target_id)
        return {
            "items": _clean(to_jsonable_python(rows)),
            "untrusted_fields": ["items"],
        }

    @kit.tool(
        "students:write",
        read_only=False,
        idempotent=False,
        limit=WRITE_LIMIT,
        log=LogSpec(keep=("student_id", "target_kind", "target_id", "visibility")),
        roles=ROLES,
    )
    async def add_comment(
        student_id: StudentId,
        target_kind: CommentTarget,
        target_id: Annotated[UUID, Field(description="Id of the object to comment.")],
        body: Annotated[str, Field(min_length=1, max_length=2000)],
        visibility: Annotated[
            Literal["student_and_staff", "staff_only"],
            Field(description="staff_only needs the staff-notes permission."),
        ] = "student_and_staff",
    ) -> dict[str, Any]:
        """Comment on a student's profile, activity, list entry or words.

        A student-visible comment notifies the student.
        """
        ctx = await staff_context(kit)
        await _in_scope(kit, ctx, student_id)
        saved = await adm.comments.add(
            ctx, student_id, target_kind, target_id, body, visibility
        )
        return {"comment": saved}

    @kit.tool(
        "students:write",
        read_only=False,
        destructive=True,
        idempotent=True,
        limit=WRITE_LIMIT,
        log=LogSpec(keep=("comment_id",)),
        roles=ROLES,
    )
    async def delete_comment(
        comment_id: Annotated[UUID, Field(description="One of the caller's comments.")],
    ) -> dict[str, Any]:
        """Delete a comment the caller wrote."""
        ctx = await staff_context(kit)
        await adm.comments.delete(ctx, comment_id)
        return {"deleted": str(comment_id)}

    @kit.tool(
        "students:write",
        read_only=False,
        idempotent=False,
        limit=WRITE_LIMIT,
        log=LogSpec(keep=("student_id", "priority", "deadline")),
        roles=ROLES,
    )
    async def assign_task(
        student_id: StudentId,
        title: Annotated[str, Field(min_length=1, max_length=TITLE_MAX)],
        description: Annotated[str, Field(max_length=DESCRIPTION_MAX)] = "",
        priority: TaskPriority = "medium",
        deadline: dt.date | None = None,
    ) -> dict[str, Any]:
        """Give a student a task; it shows as set by their counselor or mentor."""
        ctx = await staff_context(kit)
        await _in_scope(kit, ctx, student_id)
        draft = Task(
            id=new_id(),
            student_id=student_id,
            title=title,
            description=description,
            priority=priority,
            deadline=deadline,
        )
        return {"task": await adm.tasks.create(ctx, student_id, draft)}
