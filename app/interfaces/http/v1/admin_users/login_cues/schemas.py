"""Request and response models of the admin login cue routes."""

from datetime import datetime
from uuid import UUID

from app.modules.identity.application.login_cues import AdminLoginCue, NewLoginCue

from pydantic import BaseModel, Field

MAX_BULK = 500


class LoginCueBody(BaseModel):
    """One pre-registered student: EMIS login, full name and group."""

    emis_login: str = Field(min_length=1, max_length=100)
    full_name: str = Field(min_length=1, max_length=255)
    group_id: UUID

    def to_command(self) -> NewLoginCue:
        """Return the application input."""
        return NewLoginCue(
            emis_login=self.emis_login,
            full_name=self.full_name,
            group_id=self.group_id,
        )


class BulkLoginCuesBody(BaseModel):
    """Several cues at once; all of them are created or none."""

    items: list[LoginCueBody] = Field(min_length=1, max_length=MAX_BULK)


class LoginCueResponse(BaseModel):
    """A cue as the administrator sees it: the login is masked."""

    id: UUID
    full_name: str
    group_id: UUID
    group_name: str
    login_masked: str
    created_at: datetime
    consumed_at: datetime | None

    @classmethod
    def from_view(cls, view: AdminLoginCue) -> "LoginCueResponse":
        """Build the response from the application view."""
        return cls(
            id=view.id,
            full_name=view.full_name,
            group_id=view.group_id,
            group_name=view.group_name,
            login_masked=view.login_masked,
            created_at=view.created_at,
            consumed_at=view.consumed_at,
        )


class BulkLoginCuesResponse(BaseModel):
    """The created cues, in request order."""

    created: list[LoginCueResponse]
