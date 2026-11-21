"""Staff caseload, delegation, comments and privacy (`/v1/admission/*`)."""

from dataclasses import asdict
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from app.interfaces.http.v1.admission.deps import AdmissionCtx, AnyContext, ContainerDep
from app.interfaces.http.v1.admission.routes_items import _locale
from app.interfaces.http.v1.admission.schemas_staff import (
    AssignableRoleListOut,
    AssignableRoleOut,
    AssignableUserListOut,
    AssignableUserOut,
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
    CoveringOfficerIn,
    CoveringOfficerListOut,
    CoveringOfficerOut,
    DataExportOut,
    ErasedOut,
    MentoringOut,
    MentoringSwitchIn,
    PinIn,
    PinOut,
    PurposeListOut,
    PurposeOut,
    SavedViewIn,
    SavedViewListOut,
    SavedViewOut,
    SavedViewPatch,
    StaffDeadlinesOut,
    StudentDeadlineOut,
)
from app.modules.admission.application.privacy import describe_purposes
from app.modules.admission.application.staff import CaseloadFilters
from app.modules.admission.domain.today import Pin

from fastapi import APIRouter, Header, Query, Response, status

router = APIRouter(prefix="/v1/admission", tags=["admission"])


async def list_caseload(
    container: ContainerDep,
    ctx: AdmissionCtx,
    stage: Annotated[str | None, Query()] = None,
    risk: Annotated[bool, Query()] = False,
    deadline_before: Annotated[datetime | None, Query()] = None,
    group_id: Annotated[UUID | None, Query()] = None,
    scope: Annotated[Literal["mine", "all"], Query()] = "mine",
    q: Annotated[str, Query(max_length=80)] = "",
) -> CaseloadOut:
    """Students the caller reaches, soonest deadline first; `all` is admin-only."""
    filters = CaseloadFilters(stage, risk, deadline_before, group_id, scope, q)
    staff = container.admission.staff
    items = (
        await staff.all_students(ctx, filters)
        if scope == "all"
        else await staff.caseload(ctx, filters)
    )
    return CaseloadOut(items=[CaseloadItemOut.of(i) for i in items])


async def list_assignable_roles(
    container: ContainerDep,
    ctx: AdmissionCtx,
    student_id: Annotated[UUID, Query()],
) -> AssignableRoleListOut:
    """Sub-roles the caller may delegate over a student."""
    roles = await container.admission.staff.assignable_roles(ctx, student_id)
    return AssignableRoleListOut(items=[AssignableRoleOut.of(r) for r in roles])


async def search_assignable_users(
    container: ContainerDep,
    ctx: AdmissionCtx,
    student_id: Annotated[UUID, Query()],
    q: Annotated[str, Query(max_length=80)] = "",
) -> AssignableUserListOut:
    """Active counselors, mentors and officers matching a name."""
    users = await container.admission.staff.assignable_users(ctx, student_id, q)
    return AssignableUserListOut(items=[AssignableUserOut.of(u) for u in users])


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


async def list_covering_officers(
    container: ContainerDep, ctx: AnyContext
) -> CoveringOfficerListOut:
    """Officers who cover every student's transcript requests (admin only)."""
    rows = await container.admission.staff.covering_officers(ctx)
    return CoveringOfficerListOut(items=[CoveringOfficerOut.of(a, u) for a, u in rows])


async def search_officer_candidates(
    container: ContainerDep,
    ctx: AnyContext,
    q: Annotated[str, Query(max_length=80)] = "",
) -> AssignableUserListOut:
    """Active transcript officers matching a name (admin only)."""
    users = await container.admission.staff.officer_candidates(ctx, q)
    return AssignableUserListOut(items=[AssignableUserOut.of(u) for u in users])


async def cover_all_students(
    body: CoveringOfficerIn, container: ContainerDep, ctx: AnyContext
) -> CoveringOfficerOut:
    """Let an officer cover every student's transcript requests (admin only)."""
    created = await container.admission.staff.cover_all(
        ctx, body.user_id, body.expires_at
    )
    names = await container.admission.staff.covering_officers(ctx)
    user = next((u for a, u in names if a.id == created.id), None)
    return CoveringOfficerOut.of(created, user)


async def uncover_all_students(
    assignment_id: UUID, container: ContainerDep, ctx: AnyContext
) -> Response:
    """Take the all-students coverage away from an officer (admin only)."""
    await container.admission.staff.uncover_all(ctx, assignment_id)
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


async def get_mentoring(container: ContainerDep, ctx: AdmissionCtx) -> MentoringOut:
    """The caller's own mentoring switches."""
    return MentoringOut.of(await container.admission.mentoring.get(ctx))


async def set_mentee(
    body: MentoringSwitchIn, container: ContainerDep, ctx: AdmissionCtx
) -> MentoringOut:
    """An applicant shares (or stops sharing) their profile with mentors."""
    state = await container.admission.mentoring.set_mentee(ctx, body.enabled)
    return MentoringOut.of(state)


async def set_mentor(
    body: MentoringSwitchIn, container: ContainerDep, ctx: AdmissionCtx
) -> MentoringOut:
    """A mentor accepts (or stops accepting) mentorship."""
    state = await container.admission.mentoring.set_mentor(ctx, body.enabled)
    return MentoringOut.of(state)


async def staff_deadlines(
    container: ContainerDep,
    ctx: AdmissionCtx,
    scope: Annotated[Literal["mine", "all"], Query()] = "mine",
    accept_language: Annotated[str | None, Header(alias="Accept-Language")] = None,
) -> StaffDeadlinesOut:
    """Deadlines and tasks of the students the caller reaches (`mine`: assigned)."""
    rows = await container.admission.staff_timeline.get(
        ctx, scope, _locale(accept_language)
    )
    return StaffDeadlinesOut(items=[StudentDeadlineOut(**asdict(r)) for r in rows])


async def pin_action(
    student_id: UUID, body: PinIn, container: ContainerDep, ctx: AdmissionCtx
) -> PinOut:
    """Pin one action at the top of the student's Today for 14 days."""
    p = await container.admission.staff.pin(
        ctx, student_id, body.title, body.href, body.note
    )
    return _pin_out(p)


def _pin_out(p: Pin) -> PinOut:
    return PinOut(
        student_id=p.student_id,
        title=p.title,
        href=p.href,
        note=p.note,
        pinned_by=p.pinned_by_name,
        expires_at=p.expires_at,
    )


async def get_pin(
    student_id: UUID, container: ContainerDep, ctx: AdmissionCtx
) -> PinOut:
    """The pinned action in force; 404 when there is none."""
    return _pin_out(await container.admission.staff.current_pin(ctx, student_id))


async def unpin_action(
    student_id: UUID, container: ContainerDep, ctx: AdmissionCtx
) -> Response:
    """Remove the pinned action."""
    await container.admission.staff.unpin(ctx, student_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


_R = router.add_api_route
_R(
    "/staff/students",
    list_caseload,
    methods=["GET"],
    response_model=CaseloadOut,
    operation_id="admission_list_caseload",
)
_R(
    "/staff/assignable-roles",
    list_assignable_roles,
    methods=["GET"],
    response_model=AssignableRoleListOut,
    operation_id="admission_list_assignable_roles",
)
_R(
    "/staff/assignable-users",
    search_assignable_users,
    methods=["GET"],
    response_model=AssignableUserListOut,
    operation_id="admission_search_assignable_users",
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
    "/staff/all-students-officers",
    list_covering_officers,
    methods=["GET"],
    response_model=CoveringOfficerListOut,
    operation_id="admission_list_covering_officers",
)
_R(
    "/staff/all-students-officers/candidates",
    search_officer_candidates,
    methods=["GET"],
    response_model=AssignableUserListOut,
    operation_id="admission_search_officer_candidates",
)
_R(
    "/staff/all-students-officers",
    cover_all_students,
    methods=["POST"],
    status_code=status.HTTP_201_CREATED,
    response_model=CoveringOfficerOut,
    operation_id="admission_cover_all_students",
)
_R(
    "/staff/all-students-officers/{assignment_id}",
    uncover_all_students,
    methods=["DELETE"],
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="admission_uncover_all_students",
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
_R(
    "/mentoring",
    get_mentoring,
    methods=["GET"],
    response_model=MentoringOut,
    operation_id="admission_get_mentoring",
)
_R(
    "/mentoring/mentee",
    set_mentee,
    methods=["PUT"],
    response_model=MentoringOut,
    operation_id="admission_set_mentee_opt_in",
)
_R(
    "/mentoring/mentor",
    set_mentor,
    methods=["PUT"],
    response_model=MentoringOut,
    operation_id="admission_set_mentor_opt_in",
)
_R(
    "/staff/students/{student_id}/pin",
    pin_action,
    methods=["POST"],
    response_model=PinOut,
    operation_id="admission_staff_pin_action",
)
_R(
    "/staff/students/{student_id}/pin",
    unpin_action,
    methods=["DELETE"],
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="admission_staff_unpin_action",
)
_R(
    "/staff/caseload-deadlines",
    staff_deadlines,
    methods=["GET"],
    response_model=StaffDeadlinesOut,
    operation_id="admission_staff_caseload_deadlines",
)
_R(
    "/staff/students/{student_id}/pin",
    get_pin,
    methods=["GET"],
    response_model=PinOut,
    operation_id="admission_staff_get_pin",
)
