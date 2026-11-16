"""Staff caseload, delegation, comments and privacy (`/v1/admission/*`)."""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from app.interfaces.http.v1.admission.deps import AdmissionCtx, ContainerDep
from app.interfaces.http.v1.admission.schemas_staff import (
    AssignmentIn,
    AssignmentOut,
    AuditOut,
    AuditRecordOut,
    CaseloadItemOut,
    CaseloadOut,
    CommentIn,
    CommentListOut,
    CommentOut,
    ConsentIn,
    ConsentOut,
    DataExportOut,
    ErasedOut,
    PurposeListOut,
    PurposeOut,
    SavedViewIn,
    SavedViewListOut,
    SavedViewOut,
    SavedViewPatch,
)
from app.modules.admission.application.privacy import describe_purposes
from app.modules.admission.application.staff import CaseloadFilters

from fastapi import APIRouter, Query, Response, status

router = APIRouter(prefix="/v1/admission", tags=["admission"])


async def list_caseload(
    container: ContainerDep,
    ctx: AdmissionCtx,
    stage: Annotated[str | None, Query()] = None,
    risk: Annotated[bool, Query()] = False,
    deadline_before: Annotated[datetime | None, Query()] = None,
    group_id: Annotated[UUID | None, Query()] = None,
) -> CaseloadOut:
    """Students the caller reaches, soonest deadline first."""
    items = await container.admission.staff.caseload(
        ctx, CaseloadFilters(stage, risk, deadline_before, group_id)
    )
    return CaseloadOut(items=[CaseloadItemOut.of(i) for i in items])


async def create_assignment(
    body: AssignmentIn, container: ContainerDep, ctx: AdmissionCtx
) -> AssignmentOut:
    """Delegate a sub-role over a student or a class (§4.5)."""
    created = await container.admission.staff.assign(
        ctx,
        user_id=body.user_id,
        staff_role_id=body.staff_role_id,
        scope_kind=body.scope_kind,
        scope_ref=body.scope_ref,
        expires_at=body.expires_at,
    )
    return AssignmentOut.of(created)


async def revoke_assignment(
    assignment_id: UUID, container: ContainerDep, ctx: AdmissionCtx
) -> Response:
    """Revoke a delegated assignment and its children."""
    await container.admission.staff.revoke(ctx, assignment_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


async def list_saved_views(
    container: ContainerDep, ctx: AdmissionCtx
) -> SavedViewListOut:
    """The caller's saved caseload views."""
    rows = await container.admission.staff.views(ctx)
    return SavedViewListOut(items=[SavedViewOut.of(v) for v in rows])


async def create_saved_view(
    body: SavedViewIn, container: ContainerDep, ctx: AdmissionCtx
) -> SavedViewOut:
    """Save a caseload filter."""
    view = await container.admission.staff.add_view(
        ctx, body.name, body.filters, body.sort, body.is_default
    )
    return SavedViewOut.of(view)


async def update_saved_view(
    view_id: UUID, body: SavedViewPatch, container: ContainerDep, ctx: AdmissionCtx
) -> SavedViewOut:
    """Replace a saved view."""
    view = await container.admission.staff.update_view(
        ctx,
        view_id,
        name=body.name,
        filters=body.filters,
        sort=body.sort,
        is_default=body.is_default,
        lock_version=body.lock_version,
    )
    return SavedViewOut.of(view)


async def delete_saved_view(
    view_id: UUID, container: ContainerDep, ctx: AdmissionCtx
) -> Response:
    """Delete a saved view."""
    await container.admission.staff.delete_view(ctx, view_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


async def list_comments(
    student_id: Annotated[UUID, Query()],
    target_kind: Annotated[str, Query()],
    target_id: Annotated[UUID, Query()],
    container: ContainerDep,
    ctx: AdmissionCtx,
) -> CommentListOut:
    """Comments on one object the caller may see."""
    rows = await container.admission.comments.thread(
        ctx, student_id, target_kind, target_id
    )
    return CommentListOut(items=[CommentOut.of(c) for c in rows])


async def comment_inbox(container: ContainerDep, ctx: AdmissionCtx) -> CommentListOut:
    """Comments others left for the caller."""
    rows = await container.admission.comments.inbox(ctx)
    return CommentListOut(items=[CommentOut.of(c) for c in rows])


async def create_comment(
    body: CommentIn, container: ContainerDep, ctx: AdmissionCtx
) -> CommentOut:
    """Comment on an object of a student's profile."""
    saved = await container.admission.comments.add(
        ctx,
        body.student_id,
        body.target_kind,
        body.target_id,
        body.body,
        body.visibility,
        body.anchor,
    )
    return CommentOut.of(saved)


async def delete_comment(
    comment_id: UUID, container: ContainerDep, ctx: AdmissionCtx
) -> Response:
    """Delete a comment the caller wrote, or one on their own profile."""
    await container.admission.comments.delete(ctx, comment_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


async def get_consent(container: ContainerDep, ctx: AdmissionCtx) -> ConsentOut:
    """The caller's purpose consents."""
    return ConsentOut.of(await container.admission.privacy.consent(ctx))


async def list_purposes(container: ContainerDep, ctx: AdmissionCtx) -> PurposeListOut:
    """The consent purposes with titles in uz, ru and en."""
    rows = describe_purposes(container.i18n.t)
    return PurposeListOut(items=[PurposeOut(**r) for r in rows])


async def grant_consent(
    body: ConsentIn, container: ContainerDep, ctx: AdmissionCtx
) -> ConsentOut:
    """Grant purposes."""
    return ConsentOut.of(await container.admission.privacy.grant(ctx, body.purposes))


async def withdraw_consent(
    purpose: str, container: ContainerDep, ctx: AdmissionCtx
) -> ConsentOut:
    """Withdraw one purpose."""
    return ConsentOut.of(await container.admission.privacy.withdraw(ctx, purpose))


async def export_data(container: ContainerDep, ctx: AdmissionCtx) -> DataExportOut:
    """Export the caller's admission data."""
    out = await container.admission.privacy.export(ctx)
    return DataExportOut(
        generated_at=out["generated_at"],
        tables=out["tables"],
        access_log=[AuditRecordOut.of(a) for a in out["access_log"]],
    )


async def erase_data(container: ContainerDep, ctx: AdmissionCtx) -> ErasedOut:
    """Delete the caller's admission data."""
    return ErasedOut(deleted=await container.admission.privacy.erase(ctx))


async def my_audit(container: ContainerDep, ctx: AdmissionCtx) -> AuditOut:
    """Who looked at the caller's data."""
    rows = await container.admission.privacy.audit(ctx)
    return AuditOut(items=[AuditRecordOut.of(a) for a in rows])


_R = router.add_api_route
_R(
    "/staff/students",
    list_caseload,
    methods=["GET"],
    response_model=CaseloadOut,
    operation_id="admission_list_caseload",
)
_R(
    "/staff/assignments",
    create_assignment,
    methods=["POST"],
    status_code=status.HTTP_201_CREATED,
    response_model=AssignmentOut,
    operation_id="admission_create_assignment",
)
_R(
    "/staff/assignments/{assignment_id}",
    revoke_assignment,
    methods=["DELETE"],
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="admission_revoke_assignment",
)
_R(
    "/staff/saved-views",
    list_saved_views,
    methods=["GET"],
    response_model=SavedViewListOut,
    operation_id="admission_list_saved_views",
)
_R(
    "/staff/saved-views",
    create_saved_view,
    methods=["POST"],
    status_code=status.HTTP_201_CREATED,
    response_model=SavedViewOut,
    operation_id="admission_create_saved_view",
)
_R(
    "/staff/saved-views/{view_id}",
    update_saved_view,
    methods=["PATCH"],
    response_model=SavedViewOut,
    operation_id="admission_update_saved_view",
)
_R(
    "/staff/saved-views/{view_id}",
    delete_saved_view,
    methods=["DELETE"],
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="admission_delete_saved_view",
)
_R(
    "/comments",
    list_comments,
    methods=["GET"],
    response_model=CommentListOut,
    operation_id="admission_list_comments",
)
_R(
    "/comments/inbox",
    comment_inbox,
    methods=["GET"],
    response_model=CommentListOut,
    operation_id="admission_comment_inbox",
)
_R(
    "/comments",
    create_comment,
    methods=["POST"],
    status_code=status.HTTP_201_CREATED,
    response_model=CommentOut,
    operation_id="admission_create_comment",
)
_R(
    "/comments/{comment_id}",
    delete_comment,
    methods=["DELETE"],
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="admission_delete_comment",
)
_R(
    "/consent/purposes",
    list_purposes,
    methods=["GET"],
    response_model=PurposeListOut,
    operation_id="admission_list_consent_purposes",
)
_R(
    "/consent",
    get_consent,
    methods=["GET"],
    response_model=ConsentOut,
    operation_id="admission_get_consent",
)
_R(
    "/consent",
    grant_consent,
    methods=["PUT"],
    response_model=ConsentOut,
    operation_id="admission_grant_consent",
)
_R(
    "/consent/{purpose}",
    withdraw_consent,
    methods=["DELETE"],
    response_model=ConsentOut,
    operation_id="admission_withdraw_consent",
)
_R(
    "/privacy/export",
    export_data,
    methods=["GET"],
    response_model=DataExportOut,
    operation_id="admission_export_data",
)
_R(
    "/privacy/data",
    erase_data,
    methods=["DELETE"],
    response_model=ErasedOut,
    operation_id="admission_erase_data",
)
_R(
    "/privacy/audit",
    my_audit,
    methods=["GET"],
    response_model=AuditOut,
    operation_id="admission_my_audit",
)
