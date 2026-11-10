"""PUT, DELETE /v1/staff/students/{student_id}/face."""

from typing import Annotated
from uuid import UUID

from app.interfaces.http.v1.faces.deps import ContainerDep, StaffActor
from app.interfaces.http.v1.faces.handlers.upload import read_image
from app.interfaces.http.v1.faces.schemas import FaceOut

from fastapi import File, Response, UploadFile, status


async def put_student_face(
    student_id: UUID,
    file: Annotated[UploadFile, File()],
    container: ContainerDep,
    actor: StaffActor,
) -> FaceOut:
    """Set a student's face; the student cannot change it afterwards."""
    data = await read_image(file)
    view = await container.faces.staff_upload.execute(actor, student_id, data)
    return FaceOut.of(view)


async def delete_student_face(
    student_id: UUID, container: ContainerDep, actor: StaffActor
) -> Response:
    """Remove a student's face and release the lock."""
    await container.faces.staff_delete.execute(actor, student_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
