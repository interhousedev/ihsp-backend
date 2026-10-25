"""Request and response models of registration, reclaim, EMIS password and deletion."""

from datetime import date
from typing import Literal
from uuid import UUID

from app.modules.identity.application.register_start import StartedRegistration

from pydantic import BaseModel, EmailStr, Field, SecretStr

_TOKEN = Field(min_length=10, max_length=200)
_PASSWORD = Field(min_length=1, max_length=200)  # long inputs would only burn CPU


class StartRegistrationBody(BaseModel):
    """EMIS credentials of a student who wants an IHSP account."""

    emis_login: str = Field(min_length=1, max_length=100)
    emis_password: SecretStr = _PASSWORD


class RegistrationProfileResponse(BaseModel):
    """The profile imported from EMIS and the login the student will get."""

    first_name: str
    last_name: str
    middle_name: str | None
    group_name: str
    login: str


class ImportedMatchResponse(BaseModel):
    """An imported record that may be the student's."""

    first_name: str
    last_name: str
    group_name: str
    needs_confirmation: bool


class RegistrationStartResponse(BaseModel):
    """RegistrationStart of the API contract."""

    registration_token: str
    profile: RegistrationProfileResponse
    imported_match: ImportedMatchResponse | None

    @classmethod
    def from_result(cls, started: StartedRegistration) -> "RegistrationStartResponse":
        """Build the response from the use case result."""
        profile = started.profile
        match = started.imported_match
        return cls(
            registration_token=started.registration_token,
            profile=RegistrationProfileResponse(
                first_name=profile.first_name,
                last_name=profile.last_name,
                middle_name=profile.middle_name,
                group_name=profile.group_name,
                login=started.login,
            ),
            imported_match=(
                None
                if match is None
                else ImportedMatchResponse(
                    first_name=match.first_name,
                    last_name=match.last_name,
                    group_name=match.group_name,
                    needs_confirmation=match.needs_confirmation,
                )
            ),
        )


class CueGroupResponse(BaseModel):
    """A group that has unclaimed login cues."""

    group_id: UUID
    name: str


class CueOptionResponse(BaseModel):
    """A pickable student: an opaque cue id and the display name. Nothing else."""

    cue_id: UUID
    display_name: str


class StartCueRegistrationBody(BaseModel):
    """The cue the student picked and the EMIS password for its login."""

    cue_id: UUID
    emis_password: SecretStr = _PASSWORD


class SendRegistrationEmailBody(BaseModel):
    """Where to send the confirmation code."""

    registration_token: str = _TOKEN
    email: EmailStr = Field(max_length=320)


class CompleteRegistrationBody(BaseModel):
    """The password, the emailed code and the optional import confirmation."""

    registration_token: str = _TOKEN
    password: SecretStr = _PASSWORD
    email_code: str = Field(min_length=1, max_length=20)
    confirm_import_match: bool = False
    # Hydra v2+ challenges are encrypted flows, often 1-3 KB long
    login_challenge: str | None = Field(default=None, max_length=8192)


class CompleteRegistrationResponse(BaseModel):
    """The new login and where the browser continues."""

    login: str
    redirect_to: str | None
    login_ticket: str | None = None
    """Set without a login challenge: IHT ID redeems it on its own next login."""


class StartReclaimBody(StartRegistrationBody):
    """EMIS credentials of the account owner."""


class StartReclaimResponse(BaseModel):
    """The account found and the token of the reclaim."""

    reclaim_token: str
    login: str


class SendReclaimEmailBody(BaseModel):
    """Where to send the confirmation code."""

    reclaim_token: str = _TOKEN
    email: EmailStr = Field(max_length=320)


class CompleteReclaimBody(BaseModel):
    """The new password and the emailed code."""

    reclaim_token: str = _TOKEN
    new_password: SecretStr = _PASSWORD
    email_code: str = Field(min_length=1, max_length=20)


class UpdateEmisPasswordBody(BaseModel):
    """The new EMIS password."""

    emis_password: SecretStr = _PASSWORD


class EmisPasswordResponse(BaseModel):
    """The EMIS link state after the update."""

    emis_status: Literal["active", "needs_reauth"]


class DeleteAccountBody(BaseModel):
    """Confirmation of an account deletion."""

    password: SecretStr = _PASSWORD
    otp_code: str | None = Field(default=None, max_length=20)


class DeleteAccountResponse(BaseModel):
    """When the personal data is removed."""

    closes_on: date
