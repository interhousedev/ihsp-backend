"""Signed base URLs of stored HTML widgets, shared by authoring and learning.

The token format is the H5P one (course, package, expiry, HMAC) but signed with
its own key, so an H5P token never opens a widget path and the other way round.
"""

from dataclasses import dataclass
from uuid import UUID

from app.modules.lms.domain.h5p_token import sign_token, verify_token
from app.modules.lms.domain.html_widget import (
    WIDGET_ENTRY,
    WIDGET_TOKEN_SECONDS,
    WidgetPackageError,
    widget_content_type,
    widget_path,
    widget_prefix,
)
from app.modules.lms.ports.h5p_store import H5PObjectStore
from app.shared.clock import Clock

WIDGET_PATH = "/v1/lms/html-widgets"


@dataclass(frozen=True, slots=True)
class WidgetLaunch:
    """Where the frame loads the widget from, and how long the path is valid."""

    base_url: str
    entry_url: str
    expires_in: int


@dataclass(frozen=True, slots=True)
class WidgetFile:
    """One file of a widget, ready to send."""

    data: bytes
    content_type: str


class WidgetFileNotFound(LookupError):
    """The token is invalid or expired, or the file does not exist."""


class HtmlWidgetLinks:
    """Signs widget URLs and reads the files they point to."""

    def __init__(self, key: bytes, clock: Clock, store: H5PObjectStore | None) -> None:
        """Store the signing key, the clock and the object store."""
        self.key = key
        self.clock = clock
        self.store = store

    def launch(self, course_id: UUID, package_id: UUID) -> WidgetLaunch:
        """Return the signed base path (ends with ``/``) and the entry page."""
        expires = int(self.clock.now().timestamp()) + WIDGET_TOKEN_SECONDS
        token = sign_token(self.key, course_id, package_id, expires)
        base = f"{WIDGET_PATH}/{token}/"
        return WidgetLaunch(base, base + WIDGET_ENTRY, WIDGET_TOKEN_SECONDS)

    async def read(self, token: str, path: str) -> WidgetFile:
        """Return a file of the widget the token grants.

        Raises:
            WidgetFileNotFound: Bad or expired token, bad path, unknown file.
        """
        now = int(self.clock.now().timestamp())
        claims = verify_token(self.key, token, now=now)
        if claims is None or self.store is None:
            raise WidgetFileNotFound(token)
        try:
            clean = widget_path(path)
        except WidgetPackageError as exc:
            raise WidgetFileNotFound(path) from exc
        content_type = widget_content_type(clean)
        if content_type is None:
            raise WidgetFileNotFound(path)
        key = widget_prefix(claims.course_id, claims.package_id) + clean
        try:
            data = await self.store.get(key)
        except Exception as exc:  # noqa: BLE001 - any storage miss is a 404
            raise WidgetFileNotFound(path) from exc
        return WidgetFile(data, content_type)
