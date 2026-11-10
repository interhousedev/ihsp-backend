"""GET /v1/admin/users/{user_id}/face-photo."""

from uuid import UUID

from app.interfaces.http.v1.faces.deps import AdminActor, ContainerDep
from app.interfaces.http.v1.faces.schemas import FacePhotoOut


async def get_user_face_photo(
    user_id: UUID, container: ContainerDep, _admin: AdminActor
) -> FacePhotoOut:
    """A student's or teacher's face photo as a short-lived link; 404 without one."""
    return FacePhotoOut.of(await container.faces.admin_get_face.execute(user_id))
