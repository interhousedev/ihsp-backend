"""Onboarding steps and the rule that decides which of them a user sees."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID


class StepKey(StrEnum):
    """The steps of the wizard, in order."""

    SELFIE = "selfie"
    CERTIFICATES = "certificates"


@dataclass(frozen=True, slots=True)
class Step:
    """One step: ``required`` and not ``done`` keeps the wizard open."""

    key: StepKey
    required: bool
    done: bool
    skippable: bool


@dataclass(frozen=True, slots=True)
class Onboarding:
    """What a user must still go through; empty steps mean nothing to show."""

    required: bool
    steps: tuple[Step, ...]


@dataclass(slots=True)
class Progress:
    """The stored state of one user (no row means nothing was done yet)."""

    user_id: UUID
    created_at: datetime
    certificates_prompt_done_at: datetime | None = None
    completed_at: datetime | None = None


NOTHING = Onboarding(required=False, steps=())


def plan(*, is_student: bool, has_face: bool, certificates_done: bool) -> Onboarding:
    """Return the steps to show.

    The selfie is required while no face photo exists (curator's or own). The
    certificates prompt is skippable and shown once. A finished step stays in the
    list (done) only while another step is still shown; when nothing is left the
    list is empty.
    """
    if not is_student or (has_face and certificates_done):
        return NOTHING
    steps = [Step(StepKey.SELFIE, required=True, done=has_face, skippable=False)]
    if not certificates_done:
        steps.append(
            Step(StepKey.CERTIFICATES, required=False, done=False, skippable=True)
        )
    return Onboarding(
        required=any(s.required and not s.done for s in steps), steps=tuple(steps)
    )
