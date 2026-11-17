"""Comments under opportunities, their reports and the staff queue."""

from uuid import UUID

from app.interfaces.http.v1.admission.deps import (
    AdmissionCtx,
    AnyContext,
    ContainerDep,
)
from app.interfaces.http.v1.admission.schemas_opp_comments import (
    OppCommentIn,
    OppCommentListOut,
    OppCommentOut,
    OppReportIn,
    OppReportListOut,
    OppReportOut,
)
from app.modules.admission.application.opportunity_comments import (
    CommentView,
    OppCommentService,
)

from fastapi import APIRouter, Response, status

router = APIRouter(prefix="/v1/admission", tags=["admission"])
_NO = status.HTTP_204_NO_CONTENT


def _svc(container: ContainerDep) -> OppCommentService:
    return container.admission.opportunity_comments


async def list_comments(
    opportunity_id: UUID, container: ContainerDep, ctx: AnyContext
) -> OppCommentListOut:
    """Comments of an entry; hidden ones reach staff only."""
    found = await _svc(container).list(ctx, opportunity_id)
    return OppCommentListOut(items=[OppCommentOut.of(c) for c in found])


async def post_comment(
    opportunity_id: UUID,
    body: OppCommentIn,
    container: ContainerDep,
    ctx: AdmissionCtx,
) -> OppCommentOut:
    """Publish a comment at once."""
    view = await _svc(container).post(ctx, opportunity_id, body.body)
    return OppCommentOut.of(view)


async def delete_comment(
    comment_id: UUID, container: ContainerDep, ctx: AdmissionCtx
) -> Response:
    """The author deletes their comment."""
    await _svc(container).delete(ctx, comment_id)
    return Response(status_code=_NO)


async def report_comment(
    comment_id: UUID, body: OppReportIn, container: ContainerDep, ctx: AdmissionCtx
) -> Response:
    """Report a comment to the staff queue."""
    await _svc(container).report(ctx, comment_id, body.reason)
    return Response(status_code=_NO)


async def hide_comment(
    comment_id: UUID, container: ContainerDep, ctx: AnyContext
) -> OppCommentOut:
    """Hide a comment (staff)."""
    c = await _svc(container).hide(ctx, comment_id)
    return OppCommentOut.of(CommentView(c, ""))


async def unhide_comment(
    comment_id: UUID, container: ContainerDep, ctx: AnyContext
) -> OppCommentOut:
    """Restore a hidden comment (staff)."""
    c = await _svc(container).unhide(ctx, comment_id)
    return OppCommentOut.of(CommentView(c, ""))


async def list_reports(container: ContainerDep, ctx: AnyContext) -> OppReportListOut:
    """Open reports (staff)."""
    found = await _svc(container).reports(ctx)
    return OppReportListOut(items=[OppReportOut.of(r) for r in found])


async def dismiss_report(
    report_id: UUID, container: ContainerDep, ctx: AnyContext
) -> Response:
    """Close a report without touching the comment (staff)."""
    await _svc(container).dismiss(ctx, report_id)
    return Response(status_code=_NO)


_R = router.add_api_route
_R(
    "/opportunities/{opportunity_id}/comments",
    list_comments,
    methods=["GET"],
    response_model=OppCommentListOut,
    operation_id="admission_list_opportunity_comments",
)
_R(
    "/opportunities/{opportunity_id}/comments",
    post_comment,
    methods=["POST"],
    status_code=status.HTTP_201_CREATED,
    response_model=OppCommentOut,
    operation_id="admission_post_opportunity_comment",
)
_R(
    "/opportunity-comments/{comment_id}",
    delete_comment,
    methods=["DELETE"],
    status_code=_NO,
    response_class=Response,
    operation_id="admission_delete_opportunity_comment",
)
_R(
    "/opportunity-comments/{comment_id}/report",
    report_comment,
    methods=["POST"],
    status_code=_NO,
    response_class=Response,
    operation_id="admission_report_opportunity_comment",
)
_R(
    "/staff/opportunity-comments/{comment_id}/hide",
    hide_comment,
    methods=["POST"],
    response_model=OppCommentOut,
    operation_id="admission_hide_opportunity_comment",
)
_R(
    "/staff/opportunity-comments/{comment_id}/unhide",
    unhide_comment,
    methods=["POST"],
    response_model=OppCommentOut,
    operation_id="admission_unhide_opportunity_comment",
)
_R(
    "/staff/opportunities/reports",
    list_reports,
    methods=["GET"],
    response_model=OppReportListOut,
    operation_id="admission_list_opportunity_comment_reports",
)
_R(
    "/staff/opportunities/reports/{report_id}/dismiss",
    dismiss_report,
    methods=["POST"],
    status_code=_NO,
    response_class=Response,
    operation_id="admission_dismiss_opportunity_comment_report",
)
