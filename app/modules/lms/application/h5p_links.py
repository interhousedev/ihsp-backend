"""Signed base URLs of stored H5P packages, shared by authoring and learning."""

from dataclasses import dataclass
from uuid import UUID

from app.modules.lms.domain.h5p_package import (
    H5PPackageError,
    content_type_of,
    safe_path,
)
from app.modules.lms.domain.h5p_token import (
    H5P_TOKEN_SECONDS,
    package_prefix,
    sign_token,
    verify_token,
)
from app.modules.lms.ports.h5p_store import H5PObjectStore
from app.shared.clock import Clock

H5P_PATH = "/v1/lms/h5p"


@dataclass(frozen=True, slots=True)
class H5PLaunch:
    """The base path the player reads the package from, and its lifetime."""

    base_url: str
    expires_in: int


@dataclass(frozen=True, slots=True)
class H5PFile:
    """One file of a package, ready to send."""

    data: bytes
    content_type: str


class H5PFileNotFound(LookupError):
    """The token is invalid or expired, or the file does not exist."""


class H5PLinks:
    """Signs package URLs and reads the files they point to."""

    def __init__(self, key: bytes, clock: Clock, store: H5PObjectStore | None) -> None:
        """Store the signing key, the clock and the object store."""
        self.key = key
        self.clock = clock
        self.store = store

    def launch(self, course_id: UUID, package_id: UUID) -> H5PLaunch:
        """Return the signed base URL (path on the API, ends with ``/``)."""
        expires = int(self.clock.now().timestamp()) + H5P_TOKEN_SECONDS
        token = sign_token(self.key, course_id, package_id, expires)
        return H5PLaunch(f"{H5P_PATH}/{token}/", H5P_TOKEN_SECONDS)

    async def read(self, token: str, path: str) -> H5PFile:
        """Return a file of the package the token grants.

        Raises:
            H5PFileNotFound: Bad or expired token, bad path, unknown file.
        """
        now = int(self.clock.now().timestamp())
        claims = verify_token(self.key, token, now=now)
        if claims is None or self.store is None:
            raise H5PFileNotFound(token)
        try:
            clean = safe_path(path)
        except H5PPackageError as exc:
            raise H5PFileNotFound(path) from exc
        content_type = content_type_of(clean)
        if content_type is None:
            raise H5PFileNotFound(path)
        key = package_prefix(claims.course_id, claims.package_id) + clean
        try:
            data = await self.store.get(key)
        except Exception as exc:  # noqa: BLE001 - any storage miss is a 404
            raise H5PFileNotFound(path) from exc
        return H5PFile(data, content_type)
