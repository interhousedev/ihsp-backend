"""Links from the bot to the web apps (mini apps and plain pages)."""

from collections.abc import Iterable
from dataclasses import dataclass
from uuid import UUID

from app.settings import UrlsSettings
from app.shared.actor import Role


def _join(base: str, path: str) -> str:
    return f"{base.rstrip('/')}/{path.lstrip('/')}"


@dataclass(frozen=True, slots=True)
class BotUrls:
    """Public origins of the apps, built once from ``URLS__*`` settings."""

    id_app: str
    sp: str
    staff: str
    admin: str
    lms: str

    @classmethod
    def from_settings(cls, urls: UrlsSettings) -> "BotUrls":
        """Copy the origins the bot links to."""
        return cls(
            id_app=urls.id, sp=urls.sp, staff=urls.staff, admin=urls.admin, lms=urls.lms
        )

    @property
    def login(self) -> str:
        """Mini app login page (ID-19)."""
        return _join(self.id_app, "telegram/")

    @property
    def security(self) -> str:
        """Security settings of the ID service (the Not me target)."""
        return _join(self.id_app, "security/")

    @property
    def grades(self) -> str:
        """Grades page of IHSP Web."""
        return _join(self.sp, "grades/")

    @property
    def homework(self) -> str:
        """Homework page of IHSP Web."""
        return _join(self.sp, "homework/")

    @property
    def notifications(self) -> str:
        """Notification center of IHSP Web."""
        return _join(self.sp, "notifications/")

    def app_for(self, roles: Iterable[Role]) -> str:
        """Return the mini app for the roles: staff portal for teachers (BOT-8)."""
        held = set(roles)
        if Role.TEACHER in held:
            return self.staff
        if Role.STUDENT in held:
            return self.sp
        if Role.ADMIN in held:
            return self.admin
        if Role.LMS_ADMIN in held or Role.LMS_CREATOR in held:
            return self.lms
        return self.sp

    def lesson(self, roles: Iterable[Role], lesson_id: UUID) -> str:
        """Return the lesson page in the app that fits the roles."""
        held = set(roles)
        base = self.staff if Role.TEACHER in held else self.sp
        return _join(base, f"lessons/view/?id={lesson_id}")

    def staff_lesson(self, lesson_id: UUID) -> str:
        """Return the lesson page of the staff portal."""
        return _join(self.staff, f"lessons/view/?id={lesson_id}")
