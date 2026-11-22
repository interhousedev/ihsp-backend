"""Settings of the admission app (`IHSP_ADMISSION__*`)."""

from pydantic import BaseModel, Field, SecretStr


class ReadinessSettings(BaseModel):
    """Defaults of the college readiness score (admins override the weights)."""

    weights: dict[str, float] = Field(
        default_factory=lambda: {
            "major": 10.0,
            "plans": 5.0,
            "countries": 5.0,
            "list": 15.0,
            "essays": 20.0,
            "activities": 15.0,
            "tests": 10.0,
            "documents": 10.0,
            "tasks": 10.0,
        }
    )
    """Weight of each component; only the ratios matter."""

    activities_target: int = 5
    """Ready activities and honors that count as complete."""

    essays_target: int = 3
    """Essays that count as complete."""

    tests_target: int = 2
    """Tests with a received score that count as complete."""

    plans_target: int = 3
    """Goal-plan milestones that count as complete."""

    list_target: int = 6
    """Universities on the list that count as complete."""


class AdmissionSettings(BaseModel):
    """Admission platform (admission.ihsu.uz)."""

    enabled: bool = True
    """Serve the `/v1/admission` routes."""

    media_acl: str = "public-read"
    """S3 ACL of mirrored org logos and covers; empty sends none (bucket policy)."""

    eligible_grades: list[int] = Field(default_factory=lambda: [10, 11])
    """Grades whose students are entitled automatically."""

    estimates_student_visible: bool = False
    """Show admission chance estimates to students (admins may change it at runtime)."""

    scorecard_api_key: SecretStr = SecretStr("")
    """Optional College Scorecard key of the catalog importer; empty skips it."""

    runtime_cache_seconds: float = 30.0
    """How long a process caches the admin-edited runtime settings."""

    catalog_proposals_per_day: int = 100
    """Catalog proposals one user may submit in a rolling 24 hours."""

    readiness: ReadinessSettings = Field(default_factory=ReadinessSettings)
