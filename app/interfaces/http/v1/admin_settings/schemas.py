"""Request and response models of the platform settings routes."""

from typing import Annotated, Literal

from app.modules.admin.domain.platform_settings import (
    SCHOOL_NAME_MAX_LENGTH,
    SUPPORT_CONTACT_MAX_LENGTH,
    PlatformSettings,
)
from app.settings_features import FeaturesSettings
from app.shared.contracts.honours import HONOURS_MAX_FOURS_LIMIT

from pydantic import BaseModel, ConfigDict, Field

Locale = Literal["uz", "ru", "en"]


class HonoursFlagBody(BaseModel):
    """A honours rule without a parameter."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool


class HonoursMaxFoursBody(HonoursFlagBody):
    """A honours rule limiting the semester marks of 4."""

    max: int = Field(ge=0, le=HONOURS_MAX_FOURS_LIMIT)


class HonoursSerialsBody(HonoursFlagBody):
    """The school certificate serials that count as a medal certificate."""

    serials: list[Annotated[str, Field(min_length=1, max_length=32)]]


class HonoursBody(BaseModel):
    """Which rules count for the red diploma and the gold and silver medals."""

    model_config = ConfigDict(extra="forbid")

    red_diploma_max_fours: HonoursMaxFoursBody
    medal_certificate: HonoursSerialsBody
    gold_controls_all_five: HonoursFlagBody
    gold_semester_all_five: HonoursFlagBody
    silver_controls_all_five: HonoursFlagBody
    silver_semester_max_fours: HonoursMaxFoursBody


class PlatformSettingsBody(BaseModel):
    """PUT /v1/admin/settings: every editable setting."""

    model_config = ConfigDict(extra="forbid")

    school_name: str = Field(max_length=SCHOOL_NAME_MAX_LENGTH)
    support_contact: str = Field(max_length=SUPPORT_CONTACT_MAX_LENGTH)
    change_password_on_login: bool
    default_language: Locale
    honours: HonoursBody | None = Field(
        default=None, description="Left out: the saved rules stay."
    )


class PlatformSettingsResponse(PlatformSettingsBody):
    """The editable settings plus the read-only feature flags."""

    honours: HonoursBody

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
