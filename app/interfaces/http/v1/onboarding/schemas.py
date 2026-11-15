"""Response bodies of the onboarding routes."""

from typing import Literal

from app.interfaces.http.v1.certificates.schemas import CertificateEntryResponse
from app.modules.onboarding.domain.steps import Onboarding

from pydantic import BaseModel, Field


class OnboardingStepOut(BaseModel):
    """One step of the wizard."""

    key: Literal["selfie", "certificates"]
    required: bool
    done: bool
    skippable: bool


class OnboardingOut(BaseModel):
    """The steps the caller still has to see; empty for non-students."""

    required: bool = Field(description="True while a required step is not done.")
    steps: list[OnboardingStepOut]

    @classmethod
    def of(cls, state: Onboarding) -> "OnboardingOut":
        """Map the domain state."""
        return cls(
            required=state.required,
            steps=[
                OnboardingStepOut(
                    key=s.key.value,
                    required=s.required,
                    done=s.done,
                    skippable=s.skippable,
                )
                for s in state.steps
            ],
        )


class RefreshEmisOut(BaseModel):
    """The caller's certificates after the EMIS import."""

    entries: list[CertificateEntryResponse]
