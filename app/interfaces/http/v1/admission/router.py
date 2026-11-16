"""Routes of the admission app (`/v1/admission/*`)."""

from uuid import UUID

from app.interfaces.http.v1.admission.deps import AdmissionCtx, AnyContext, ContainerDep
from app.interfaces.http.v1.admission.schemas import (
    AdmissionConfigOut,
    AdmissionMeOut,
    CourseIncludedIn,
    CourseListOut,
    CourseOut,
    ManualCourseIn,
)
from app.modules.admission.application.config import get_me
from app.modules.admission.domain.courses import Course

from fastapi import APIRouter, status

router = APIRouter(prefix="/v1/admission", tags=["admission"])


async def get_config(container: ContainerDep, ctx: AdmissionCtx) -> AdmissionConfigOut:
    """Questions, option lists, limits and sub-roles of the admission app."""
    return AdmissionConfigOut.of(await container.admission.config.execute())


async def get_admission_me(container: ContainerDep, ctx: AnyContext) -> AdmissionMeOut:
    """The caller's role, entitlement and assignments (never refused)."""
    return AdmissionMeOut.of(get_me(ctx, container.clock.now()))


async def list_my_courses(container: ContainerDep, ctx: AdmissionCtx) -> CourseListOut:
    """The caller's merged courses."""
    rows = await container.admission.courses.list(ctx, ctx.user_id)
    return CourseListOut(items=[CourseOut.of(c) for c in rows])


async def list_student_courses(
    student_id: UUID, container: ContainerDep, ctx: AdmissionCtx
) -> CourseListOut:
    """A student's merged courses (staff in scope or the student)."""
    rows = await container.admission.courses.list(ctx, student_id)
    return CourseListOut(items=[CourseOut.of(c) for c in rows])


async def add_manual_course(
    body: ManualCourseIn, container: ContainerDep, ctx: AdmissionCtx
) -> CourseOut:
    """Add a course taken elsewhere."""
    course = Course(
        student_id=ctx.user_id,
        source="manual",
        source_ref=None,
        title=body.title.strip(),
        provider=body.provider,
        level=body.level,
        year=body.year,
        grade=body.grade,
    )
    return CourseOut.of(await container.admission.courses.add_manual(ctx, course))


async def add_lms_course(
    lms_course_id: UUID, container: ContainerDep, ctx: AdmissionCtx
) -> CourseOut:
    """Store a snapshot of one of the caller's LMS courses (idempotent)."""
    row = await container.admission.courses.add_from_lms(ctx, lms_course_id)
    return CourseOut.of(row)


async def set_course_included(
    course_id: UUID, body: CourseIncludedIn, container: ContainerDep, ctx: AdmissionCtx
) -> CourseOut:
    """Include or exclude a course."""
    row = await container.admission.courses.set_included(ctx, course_id, body.included)
    return CourseOut.of(row)


router.add_api_route(
    "/config",
    get_config,
    methods=["GET"],
    response_model=AdmissionConfigOut,
    operation_id="admission_get_config",
)
router.add_api_route(
    "/me",
    get_admission_me,
    methods=["GET"],
    response_model=AdmissionMeOut,
    operation_id="admission_get_me",
)
router.add_api_route(
    "/courses",
    list_my_courses,
    methods=["GET"],
    response_model=CourseListOut,
    operation_id="admission_list_my_courses",
)
router.add_api_route(
    "/courses",
    add_manual_course,
    methods=["POST"],
    status_code=status.HTTP_201_CREATED,
    response_model=CourseOut,
    operation_id="admission_add_manual_course",
)
router.add_api_route(
    "/courses/lms/{lms_course_id}",
    add_lms_course,
    methods=["POST"],
    status_code=status.HTTP_201_CREATED,
    response_model=CourseOut,
    operation_id="admission_add_lms_course",
)
router.add_api_route(
    "/courses/{course_id}",
    set_course_included,
    methods=["PATCH"],
    response_model=CourseOut,
    operation_id="admission_set_course_included",
)
router.add_api_route(
    "/students/{student_id}/courses",
    list_student_courses,
    methods=["GET"],
    response_model=CourseListOut,
    operation_id="admission_list_student_courses",
)
