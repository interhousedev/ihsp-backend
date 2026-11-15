"""Request and response models of the server migration routes."""

from datetime import datetime
from typing import Literal

from app.modules.admin.domain.migration import STEPS, MigrationState

from pydantic import BaseModel, ConfigDict, Field, SecretStr

StepState = Literal["pending", "running", "done"]


class MigrationStep(BaseModel):
    """One step of the copy with its progress."""

    key: str
    state: StepState


class MigrationStatusResponse(BaseModel):
    """The migration in progress; `phase` is ``idle`` when there is none."""

    configured: bool
    phase: str
    migration_id: str | None
    target_host: str | None
    target_port: int | None
    target_url: str | None
    requested_at: datetime | None
    updated_at: datetime | None
    error: str | None
    dry_run: bool
    stale: bool
    steps: list[MigrationStep]

    @classmethod
    def of(
        cls, state: MigrationState | None, *, configured: bool, stale: bool
    ) -> "MigrationStatusResponse":
        """Map the state; no state means idle."""
        done = set(state.steps_done) if state else set()
        steps = [
            MigrationStep(
                key=key,
                state=(
                    "done"
                    if key in done
                    else "running" if state and state.step == key else "pending"
                ),
            )
            for key in STEPS
        ]
        return cls(
            configured=configured,
            phase=state.phase.value if state else "idle",
            migration_id=state.id if state else None,
            target_host=state.target_host if state else None,
            target_port=state.target_port if state else None,
            target_url=state.target_url if state else None,
            requested_at=state.requested_at if state else None,
            updated_at=state.updated_at if state else None,
            error=state.error if state else None,
            dry_run=state.dry_run if state else False,
            stale=stale,
            steps=steps,
        )


class StartMigrationBody(BaseModel):
    """The target server and its one-time pairing token."""

    model_config = ConfigDict(extra="forbid")

    target_host: str = Field(min_length=1, max_length=253)
    target_port: int = Field(default=22, ge=1, le=65535)
    pairing_token: SecretStr
    target_url: str | None = Field(default=None, max_length=300)
    otp_code: str = Field(min_length=4, max_length=12)


class RollbackBody(BaseModel):
    """Step-up code for leaving maintenance mode."""

    model_config = ConfigDict(extra="forbid")

    otp_code: str = Field(min_length=4, max_length=12)
