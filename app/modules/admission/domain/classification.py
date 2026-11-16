"""Reach, target or safety for one list entry, and the balance of a list.

Pure and deterministic. The computed label starts from the estimate label (the
published acceptance rate) and moves by one step for each profile signal that
clearly weakens or strengthens the application. A student's own bucket wins over
the computed label, and a counselor's override wins over both.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Final, Literal

from app.modules.admission.domain.chooser import CatalogInstitution
from app.modules.admission.domain.estimates import LOW_RATE

LABELS: Final = ("reach", "target", "safety")
LabelSource = Literal["staff", "student", "computed", "none"]
BalanceStatus = Literal["empty", "too_few", "no_safety", "too_many_reach", "balanced"]

GPA_STRONG: Final = 0.9
"""Share of the top of the scale from which a GPA counts as strong."""
GPA_LOW: Final = 0.7
"""Share of the top of the scale below which a GPA counts as low."""
MIN_LIST: Final = 4
"""Fewer entries than this is too short a list to judge its balance."""
MAX_REACH_SHARE: Final = 0.5
"""More than this share of reach entries tips the list."""


@dataclass(frozen=True, slots=True)
class StudentSignals:
    """What the profile says about grades and tests; None when not answered."""

    gpa_ratio: float | None = None
    english: Literal["taken", "planned", "none"] | None = None
    sat_act: Literal["taken", "planned", "not_planning"] | None = None


@dataclass(frozen=True, slots=True)
class Classification:
    """The label in force, where it comes from and why it was computed so."""

    computed: str | None
    effective: str | None
    source: LabelSource
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Balance:
    """Counts per label and a verdict on the list's spread."""

    reach: int
    target: int
    safety: int
    unlabelled: int
    status: BalanceStatus


def _gpa_ratio(value: Any) -> float | None:
    """Normalise a GPA on the 5, 10 or 100 point scale to 0..1."""
    if isinstance(value, bool) or not isinstance(value, int | float) or value <= 0:
        return None
    for top in (5, 10, 100):
        if value <= top:
            return float(value) / top
    return None


def _options(value: Any) -> set[str]:
    if not isinstance(value, list):
        return set()
    return {v for v in value if isinstance(v, str)}


def signals_of(answers: Mapping[str, Any]) -> StudentSignals:
    """Read GPA (q10), English tests (q14) and SAT/ACT (q15) from the answers."""
    english_opts = _options(answers.get("q14"))
    english: Literal["taken", "planned", "none"] | None = None
    if english_opts & {"ielts", "toefl", "duolingo"}:
        english = "taken"
    elif "planned" in english_opts:
        english = "planned"
    elif "none" in english_opts:
        english = "none"
    sat_opts = _options(answers.get("q15"))
    sat: Literal["taken", "planned", "not_planning"] | None = None
    for option in ("taken", "planned", "not_planning"):
        if option in sat_opts:
            sat = option
            break
    return StudentSignals(_gpa_ratio(answers.get("q10")), english, sat)


def computed_label(
    inst: CatalogInstitution, baseline: str, signals: StudentSignals | None
) -> tuple[str | None, tuple[str, ...]]:
    """The label from the baseline estimate and the profile, with reason codes.

    Without a baseline (no published rate, or an unreviewed institution) nothing
    is computed. Without signals (the viewer may not read the profile) the
    baseline stands.
    """
    if baseline not in LABELS:
        return None, ("no_rate",)
    step = LABELS.index(baseline)
    reasons: list[str] = [f"rate_{baseline}"]
    if signals is not None:
        if signals.gpa_ratio is not None and signals.gpa_ratio < GPA_LOW:
            step -= 1
            reasons.append("gpa_low")
        elif signals.gpa_ratio is not None and signals.gpa_ratio >= GPA_STRONG:
            if baseline == "reach" and _rate_of(inst) >= LOW_RATE:
                step += 1
                reasons.append("gpa_strong")
        policy = inst.fact("test_policy")
        if (
            policy is not None
            and policy.value == "required"
            and signals.sat_act == "not_planning"
        ):
            step -= 1
            reasons.append("test_required_missing")
        if signals.english == "none":
            step -= 1
            reasons.append("english_missing")
    step = max(0, min(len(LABELS) - 1, step))
    return LABELS[step], tuple(reasons)


def _rate_of(inst: CatalogInstitution) -> float:
    for key in ("acceptance_rate_international", "acceptance_rate"):
        f = inst.fact(key)
        if f is not None and isinstance(f.value, dict):
            vals = [
                float(v)
                for v in (f.value.get("min"), f.value.get("max"))
                if isinstance(v, int | float)
            ]
            if vals:
                return sum(vals) / len(vals)
    return 0.0


def classify(
    inst: CatalogInstitution,
    baseline: str,
    signals: StudentSignals | None,
    *,
    bucket: str | None,
    override: str | None,
) -> Classification:
    """Staff override, then the student's bucket, then the computed label."""
    computed, reasons = computed_label(inst, baseline, signals)
    if override in LABELS:
        return Classification(computed, override, "staff", reasons)
    if bucket in LABELS:
        return Classification(computed, bucket, "student", reasons)
    if computed is not None:
        return Classification(computed, computed, "computed", reasons)
    return Classification(None, None, "none", reasons)


def balance(labels: Iterable[str | None]) -> Balance:
    """Judge the spread: some safety, not mostly reach, long enough to judge."""
    counts = dict.fromkeys(LABELS, 0)
    unlabelled = 0
    for label in labels:
        if label in counts:
            counts[label] += 1
        else:
            unlabelled += 1
    total = sum(counts.values()) + unlabelled
    status: BalanceStatus
    if total == 0:
        status = "empty"
    elif total < MIN_LIST:
        status = "too_few"
    elif counts["safety"] == 0:
        status = "no_safety"
    elif counts["reach"] > total * MAX_REACH_SHARE:
        status = "too_many_reach"
    else:
        status = "balanced"
    return Balance(
        counts["reach"], counts["target"], counts["safety"], unlabelled, status
    )
