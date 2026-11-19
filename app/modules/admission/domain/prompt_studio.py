"""Prompt studio: the four editable essay-reviewer prompt slots and test helpers."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final, Literal

from app.shared.ai_tasks import AiTask

MAX_SAMPLES: Final = 3
MAX_SAMPLE_CHARS: Final = 20_000
MAX_PROMPT_CONTEXT_CHARS: Final = 4_000
DAILY_RUNS: Final = 30
WINDOW_SECONDS: Final = 86_400

SlotKind = Literal["base", "uni", "check", "feedback"]
Severity = Literal["error", "warning"]

# Terms a fair reviewer prompt should name when it forbids bias.
_FAIRNESS_TERMS: Final = (
    "gender",
    "race",
    "ethnic",
    "religio",
    "nationalit",
    "disabilit",
    "sexual orientation",
    "income",
    "immigration",
)
_MIN_FAIRNESS_TERMS: Final = 5
BLOCKING_REASONS: Final = frozenset(
    {"empty", "too_long", "unknown_placeholder", "bad_format"}
)


@dataclass(frozen=True, slots=True)
class StudioSlot:
    """One editable reviewer prompt slot."""

    task: AiTask
    name: str
    kind: SlotKind


SLOTS: Final[tuple[StudioSlot, ...]] = (
    StudioSlot(AiTask.ADMIT_ESSAY_REVIEW, "base", "base"),
    StudioSlot(AiTask.ADMIT_ESSAY_UNI_REVIEW, "uni", "uni"),
    StudioSlot(AiTask.ADMIT_ESSAY_COACH, "check", "check"),
    StudioSlot(AiTask.ADMIT_ESSAY_COACH, "feedback", "feedback"),
)


def find_slot(task: str, name: str) -> StudioSlot | None:
    """The whitelisted slot for a task and name, else None."""
    for slot in SLOTS:
        if slot.task.value == task and slot.name == name:
            return slot
    return None


@dataclass(frozen=True, slots=True)
class PromptIssue:
    """One finding of the draft validation."""

    severity: Severity
    code: str
    detail: str = ""


def prompt_issues(reason: str | None, text: str) -> tuple[PromptIssue, ...]:
    """Findings for a draft: the registry's blocking reason or a fairness warning."""
    if reason is not None:
        return (PromptIssue("error", reason),)
    lowered = text.lower()
    named = sum(1 for term in _FAIRNESS_TERMS if term in lowered)
    if named < _MIN_FAIRNESS_TERMS:
        return (PromptIssue("warning", "missing_fairness"),)
    return ()


def blocking(issues: tuple[PromptIssue, ...]) -> tuple[PromptIssue, ...]:
    """Only the findings that stop a test run or a save."""
    return tuple(i for i in issues if i.severity == "error")


@dataclass(frozen=True, slots=True)
class SlotInfo:
    """A slot as the registry describes it."""

    task: str
    name: str
    summary: str
    template: bool
    fields: tuple[str, ...]
    builtin: str


@dataclass(frozen=True, slots=True)
class ActivePrompt:
    """The text in force for a slot and locale (version 0 is the built-in)."""

    text: str
    version: int
    hash: str


@dataclass(frozen=True, slots=True)
class PromptVersionInfo:
    """One stored version of a slot."""

    version: int
    locale: str
    text: str
    hash: str
    active: bool
    note: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class SlotState:
    """A slot with its active text and version history."""

    slot: SlotInfo
    active: ActivePrompt
    versions: tuple[PromptVersionInfo, ...]


@dataclass(frozen=True, slots=True)
class SampleInput:
    """A pasted essay or a library exemplar to run a prompt on."""

    text: str | None = None
    exemplar_id: Any = None
    prompt_text: str = ""
    kind: str = "personal_statement"


@dataclass(frozen=True, slots=True)
class StudioRun:
    """The output of one model run, serialised."""

    model: str
    output: dict[str, Any]


@dataclass(frozen=True, slots=True)
class RunDelta:
    """How the draft's result differs from the active one."""

    score_delta: int | None
    band_before: str | None
    band_after: str | None
    band_changed: bool


def _score(output: dict[str, Any]) -> int | None:
    value = output.get("score", output.get("alignment"))
    return value if isinstance(value, int) else None


def delta_of(active: dict[str, Any], draft: dict[str, Any]) -> RunDelta:
    """Score and band change from the active run to the draft run."""
    before, after = _score(active), _score(draft)
    band_before, band_after = active.get("band"), draft.get("band")
    return RunDelta(
        score_delta=None if before is None or after is None else after - before,
        band_before=band_before,
        band_after=band_after,
        band_changed=band_before != band_after,
    )
