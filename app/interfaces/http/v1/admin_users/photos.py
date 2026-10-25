"""Photos in the user routes: upload reading and responses with the photo link."""

from collections.abc import Sequence

from app.interfaces.http.v1.admin_users.schemas import AdminUserResponse
from app.modules.identity.domain.photo import MAX_PHOTO_BYTES
from app.modules.identity.domain.user import User
from app.modules.identity.wiring_auth import AuthServices

from fastapi import UploadFile


async def user_response(auth: AuthServices, user: User) -> AdminUserResponse:
    """One user with the link to their photo."""
    return AdminUserResponse.of(user, await auth.photo_urls.url(user.photo_file_id))


async def user_responses(
    auth: AuthServices, users: Sequence[User]
) -> list[AdminUserResponse]:
    """A page of users; the links are resolved once for the whole page."""
    urls = await auth.photo_urls.of_users(users)
    return [AdminUserResponse.of(user, urls.get(user.id)) for user in users]


async def read_photo(file: UploadFile) -> bytes:
    """Read the upload, but one byte more than the limit is never needed.

    The domain check then tells an oversized photo from a small one.
    """
    return await file.read(MAX_PHOTO_BYTES + 1)
