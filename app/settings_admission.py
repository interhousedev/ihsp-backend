"""Settings of the admission app (`IHSP_ADMISSION__*`)."""

from pydantic import BaseModel, Field, SecretStr


class GuestLinkSettings(BaseModel):
    """Defaults of the guest links a student shares with outside helpers."""

    ttl_days: int = 14
    """Days a new guest link stays valid."""

    max_sessions: int = 5
    """Browser sessions one guest link may open."""

    max_active_per_student: int = 5
    """Live guest links one student may hold."""


class AdmissionSettings(BaseModel):
    """Admission platform (admission.ihsu.uz)."""

    enabled: bool = True
    """Serve the `/v1/admission` routes."""

    eligible_grades: list[int] = Field(default_factory=lambda: [10, 11])
    """Grades whose students are entitled automatically."""

    estimates_student_visible: bool = False
    """Show admission chance estimates to students (admins may change it at runtime)."""

    scorecard_api_key: SecretStr = SecretStr("")
    """Optional College Scorecard key of the catalog importer; empty skips it."""

    runtime_cache_seconds: float = 30.0
    """How long a process caches the admin-edited runtime settings."""

    guest_links: GuestLinkSettings = Field(default_factory=GuestLinkSettings)
