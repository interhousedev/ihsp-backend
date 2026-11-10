"""A curator or an administrator sets or removes a student's face."""

from uuid import UUID

from app.modules.faces.application.enroll import FaceEnroller
from app.modules.faces.application.face_queries import GetMyFace
from app.modules.faces.application.views import FaceView
from app.modules.faces.domain.errors import (
    FaceNotCuratorError,
    FaceStudentNotFoundError,
)
from app.modules.faces.ports.directory import StudentDirectory
from app.shared.actor import Actor, Role


class StaffFaceGuard:
    """Only the curator of the student's group and administrators may act."""

    def __init__(self, *, directory: StudentDirectory) -> None:
        """Store the dependency."""
        self._directory = directory

    async def check(self, actor: Actor, student_id: UUID) -> None:
        """Raise unless the actor may manage this student's face."""
        student = await self._directory.student(student_id)
        if student is None:
            raise FaceStudentNotFoundError()
        if actor.has(Role.ADMIN):
            return
        if not await self._directory.curates(actor.user_id, student.group_id):
            raise FaceNotCuratorError()


class StaffUploadFace:
    """Set the student's face and lock it against the student."""

    def __init__(
        self, *, guard: StaffFaceGuard, enroller: FaceEnroller, reader: GetMyFace
    ) -> None:
        """Store the dependencies."""
        self._guard = guard
        self._enroller = enroller
        self._reader = reader

    async def execute(self, actor: Actor, student_id: UUID, data: bytes) -> FaceView:
        """Save (or replace) the face and lock it."""
        await self._guard.check(actor, student_id)
        await self._enroller.enroll(
            student_id, uploaded_by=actor.user_id, data=data, by_staff=True
        )
        return await self._reader.execute(student_id)


class StaffDeleteFace:
    """Remove the student's face."""

    def __init__(self, *, guard: StaffFaceGuard, enroller: FaceEnroller) -> None:
        """Store the dependencies."""
        self._guard = guard
        self._enroller = enroller

    async def execute(self, actor: Actor, student_id: UUID) -> None:
        """Delete the face, locked or not."""
        await self._guard.check(actor, student_id)
        await self._enroller.remove(student_id, by_staff=True)
