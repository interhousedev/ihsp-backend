"""Port: the user's profile photo (identity), which a new face also becomes."""

from typing import Literal, Protocol
from uuid import UUID

PhotoSource = Literal["none", "face", "other"]


class ProfilePhotos(Protocol):
    """Copies faces to the profile photo that avatars across the apps show."""

    async def source(self, user_id: UUID) -> PhotoSource:
        """Say whether the user has no photo, a face copy or a photo set otherwise."""
        ...

    async def set_photo(self, user_id: UUID, data: bytes) -> None:
        """Make the image the user's profile photo as a face copy."""
        ...

    async def remove_photo(self, user_id: UUID) -> None:
        """Remove the user's profile photo."""
        ...
