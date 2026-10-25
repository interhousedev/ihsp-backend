"""Request and response models of the platform settings routes."""

from typing import Literal

from app.modules.admin.domain.platform_settings import (
    SCHOOL_NAME_MAX_LENGTH,
    SUPPORT_CONTACT_MAX_LENGTH,
    PlatformSettings,
)
from app.settings_features import FeaturesSettings

from pydantic import BaseModel, ConfigDict, Field

Locale = Literal["uz", "ru", "en"]


class PlatformSettingsBody(BaseModel):
    """PUT /v1/admin/settings: every editable setting."""

    model_config = ConfigDict(extra="forbid")

    school_name: str = Field(max_length=SCHOOL_NAME_MAX_LENGTH)
    support_contact: str = Field(max_length=SUPPORT_CONTACT_MAX_LENGTH)
    change_password_on_login: bool
    default_language: Locale


class PlatformSettingsResponse(PlatformSettingsBody):
    """The editable settings plus the read-only feature flags."""

    features: dict[str, bool] = Field(
        description="Feature flags of the deployment (IHSP_FEATURES__*); read-only."
    )

    @classmethod
    def of(
        cls, current: PlatformSettings, features: FeaturesSettings
    ) -> "PlatformSettingsResponse":
        """Combine the stored settings with the environment's feature flags."""
        return cls(
            **current.as_stored(),
            features={
                name: bool(getattr(features, name))
                for name in type(features).model_fields
            },
        )
