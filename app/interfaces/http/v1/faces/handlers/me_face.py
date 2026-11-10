"""GET, PUT, DELETE /v1/me/face."""

from typing import Annotated

from app.interfaces.http.v1.faces.deps import ContainerDep, StudentActor
from app.interfaces.http.v1.faces.handlers.upload import read_image
from app.interfaces.http.v1.faces.schemas import FaceOut

from fastapi import File, Response, UploadFile, status


async def get_my_face(container: ContainerDep, actor: StudentActor) -> FaceOut:
    """Whether the caller has a face on file and whether staff locked it."""
    return FaceOut.of(await container.faces.get_my_face.execute(actor.user_id))


async def put_my_face(
    file: Annotated[UploadFile, File()], container: ContainerDep, actor: StudentActor
) -> FaceOut:
    """Upload the caller's face (JPEG or PNG, up to 5 MB, exactly one face)."""
    data = await read_image(file)
    view = await container.faces.upload_my_face.execute(actor.user_id, data)
    return FaceOut.of(view)


async def delete_my_face(container: ContainerDep, actor: StudentActor) -> Response:
    """Remove the caller's face; refused while staff hold it."""
    await container.faces.delete_my_face.execute(actor.user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
