"""Courses on a student's profile: academic subjects, LMS snapshots, manual rows."""

from dataclasses import replace
from uuid import UUID

from app.modules.admission.application.access import AccessPolicy
from app.modules.admission.application.actor import AdmissionContext
from app.modules.admission.domain.courses import Course, merge
from app.modules.admission.domain.errors import (
    AdmissionForbiddenError,
    AdmissionNotFoundError,
)
from app.modules.admission.domain.permissions import Permission
from app.modules.admission.ports.courses import CourseSources
from app.modules.admission.ports.unit_of_work import UowFactory


class CourseService:
    """List, add and include or exclude courses."""

    def __init__(
        self, uow_factory: UowFactory, access: AccessPolicy, sources: CourseSources
    ) -> None:
        """Keep the transaction factory, the access policy and the sources."""
        self._uow = uow_factory
        self._access = access
        self._sources = sources

    async def _owner(self, ctx: AdmissionContext) -> None:
        """Allow only the entitled student to change their own courses."""
        resolution = await self._access.resolve(ctx, ctx.user_id)
        if not resolution.owner:
            raise AdmissionForbiddenError(params={"permission": "courses:edit"})

    async def list(self, ctx: AdmissionContext, student_id: UUID) -> list[Course]:
        """Return the merged list; the owner's view stores new live courses.

        Storing gives every academic subject and LMS enrolment an id, so the owner
        can exclude it. Staff see the stored LMS snapshots only.
        """
        resolution = await self._access.require(
            ctx, student_id, Permission.PROFILE_READ, object_type="courses"
        )
        live = await self._sources.academic_courses(student_id)
        if resolution.owner:
            live = live + await self._sources.lms_courses(ctx.actor)
        async with self._uow() as uow:
            stored = await uow.courses.list_for(student_id)
            known = {c.key for c in stored}
            fresh = [c for c in live if c.key not in known]
            if resolution.owner and fresh:
                stored = stored + [await uow.courses.add(c) for c in fresh]
                await uow.commit()
        return merge(live, stored)

    async def add_manual(self, ctx: AdmissionContext, course: Course) -> Course:
        """Add a course the student took elsewhere."""
        await self._owner(ctx)
        async with self._uow() as uow:
            row = await uow.courses.add(
                replace(
                    course, student_id=ctx.user_id, source="manual", source_ref=None
                )
            )
            await uow.commit()
        return row

    async def add_from_lms(self, ctx: AdmissionContext, lms_course_id: UUID) -> Course:
        """Store a snapshot of one of the caller's LMS courses (idempotent)."""
        await self._owner(ctx)
        ref = str(lms_course_id)
        match = next(
            (
                c
                for c in await self._sources.lms_courses(ctx.actor)
                if c.source_ref == ref
            ),
            None,
        )
        if match is None:
            raise AdmissionNotFoundError()
        async with self._uow() as uow:
            existing = await uow.courses.find(ctx.user_id, "lms", ref)
            if existing is not None:
                return existing
            row = await uow.courses.add(replace(match, student_id=ctx.user_id))
            await uow.commit()
        return row

    async def set_included(
        self, ctx: AdmissionContext, course_id: UUID, included: bool
    ) -> Course:
        """Include or exclude a stored course from the profile."""
        await self._owner(ctx)
        async with self._uow() as uow:
            row = await uow.courses.get(course_id)
            if row is None or row.student_id != ctx.user_id:
                raise AdmissionNotFoundError()
            row = await uow.courses.set_included(course_id, included)
            await uow.commit()
        return row
