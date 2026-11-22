"""Request and response models of /v1/admin/essay-keys."""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from app.modules.admission.application.essay_keys import EssayKeysStatus, RestoreReport
from app.modules.admission.ports.essay_keys import EssayKeyLedgerState

from pydantic import BaseModel, Field

MIN_PASSPHRASE = 12


class PassphraseBody(BaseModel):
    """The passphrase that seals the backup (kept by the admin, never stored)."""

    passphrase: str = Field(min_length=MIN_PASSPHRASE, max_length=1024)


class RestoreBody(BaseModel):
    """The backup file (its JSON object) and its passphrase."""

    backup: dict[str, Any]
    passphrase: str = Field(min_length=1, max_length=1024)


class RotationResponse(BaseModel):
    """Progress of the last (or running) rotation."""

    state: Literal["idle", "running", "done", "failed"]
    total: int
    done: int
    unreadable: int
    started_at: datetime | None
    finished_at: datetime | None


class EssayKeysStatusResponse(BaseModel):
    """Keys, generation, backup and rotation."""

    students_with_keys: int | None
    generation: int
    exported_at: datetime | None
    exported_by: UUID | None
    rotation: RotationResponse

    @classmethod
    def build(
        cls, ledger: EssayKeyLedgerState, students: int | None
    ) -> "EssayKeysStatusResponse":
        """From the ledger and the key count (None when unknown)."""
        r = ledger.rotation
        return cls(
            students_with_keys=students,
            generation=ledger.generation,
            exported_at=ledger.exported_at,
            exported_by=ledger.exported_by,
            rotation=RotationResponse(
                state=r.state,
                total=r.total,
                done=r.done,
                unreadable=r.unreadable,
                started_at=r.started_at,
                finished_at=r.finished_at,
            ),
        )

    @classmethod
    def from_status(cls, status: EssayKeysStatus) -> "EssayKeysStatusResponse":
        """From the status use case."""
        return cls.build(status.ledger, status.students_with_keys)


class RestoreResponse(BaseModel):
    """Keys written, keys already present, students whose stored key differs."""

    restored: int
    skipped: int
    conflicts: list[UUID]

    @classmethod
    def from_report(cls, report: RestoreReport) -> "RestoreResponse":
        """From the restore use case."""
        return cls(
            restored=report.restored,
            skipped=report.skipped,
            conflicts=report.conflicts,
        )
