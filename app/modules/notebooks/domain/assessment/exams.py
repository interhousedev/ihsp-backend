"""Exam section quotas: the share of each section and domain in a full mock.

An exam is recognised from the request or the source profiles (e.g. "SAT"). Its
sections split the count by weight, and each section's domains split the section;
the blueprint then fills each domain with the templates of the section's modes.
Unknown exams get no quota: the blueprint spreads the slots over the sources'
domains as before.
"""

import math
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from app.modules.notebooks.domain.assessment.profile import SourceProfile


@dataclass(frozen=True, slots=True)
class DomainWeight:
    """A domain of a section with its weight and the words that name it."""

    name: str
    weight: float
    aliases: tuple[str, ...] = ()
    templates: tuple[str, ...] = ()  # quiz templates; empty: the section's modes'


@dataclass(frozen=True, slots=True)
class Section:
    """A section of an exam."""

    name: str
    weight: float
    modes: tuple[str, ...]  # whose templates write its items
    kinds: tuple[str, ...]  # source kinds that feed it
    domains: tuple[DomainWeight, ...]


@dataclass(frozen=True, slots=True)
class Exam:
    """An exam and how it is recognised."""

    name: str
    pattern: str
    sections: tuple[Section, ...]


@dataclass(frozen=True, slots=True)
class DomainQuota:
    """How many slots one domain gets and how they are written."""

    domain: str
    section: str
    count: int
    modes: tuple[str, ...]
    kinds: tuple[str, ...]
    aliases: tuple[str, ...]
    templates: tuple[str, ...] = ()


EXAMS: Final[tuple[Exam, ...]] = (
    Exam(
        "SAT",
        r"\bsat\b",
        (
            Section(
                "Reading and Writing",
                0.5,
                ("reading_test", "vocab_test"),
                ("reading_passages", "vocabulary_list", "exam_paper"),
                (
                    DomainWeight(
                        "Craft and Structure",
                        0.28,
                        ("craft", "structure", "vocab", "word", "context"),
                        ("word_in_context", "purpose_structure", "cross_text"),
                    ),
                    DomainWeight(
                        "Information and Ideas",
                        0.26,
                        ("information", "ideas", "central", "evidence", "inference"),
                        ("main_idea", "inference", "evidence"),
                    ),
                    DomainWeight(
                        "Standard English Conventions",
                        0.26,
                        ("convention", "grammar", "punctuation", "boundar"),
                        ("boundaries", "form_structure_sense"),
                    ),
                    DomainWeight(
                        "Expression of Ideas",
                        0.2,
                        ("expression", "transition", "rhetoric", "synthesis"),
                        ("transitions", "rhetorical_synthesis"),
                    ),
                ),
            ),
            Section(
                "Math",
                0.5,
                ("problem_practice",),
                ("problem_set", "formula_sheet", "exam_paper"),
                (
                    DomainWeight("Algebra", 0.35, ("algebra", "linear")),
                    DomainWeight(
                        "Advanced Math", 0.35, ("advanced", "quadratic", "nonlinear")
                    ),
                    DomainWeight(
                        "Problem-Solving and Data Analysis",
                        0.15,
                        ("problem-solving", "data", "statistic", "percent", "psda"),
                    ),
                    DomainWeight(
                        "Geometry and Trigonometry",
                        0.15,
                        ("geometry", "trigonometr", "triangle", "circle"),
                    ),
                ),
            ),
        ),
    ),
)
QUOTA_MODES: Final = frozenset({"full_mock", "topic_test"})


def _sections_fed(exam: Exam, profiles: Sequence[SourceProfile]) -> int:
    kinds = {p.kind for p in profiles}
    return sum(1 for section in exam.sections if kinds & set(section.kinds))


def exam_for(
    mode: str, prompt: str | None, profiles: Sequence[SourceProfile]
) -> Exam | None:
    """The exam a test prepares for, or None (no quotas).

    A full mock names the exam in the request or the sources' subjects. A mixed
    topic test ("make me a sat test" over math and reading sources) counts as a
    mock when the request names the exam and the sources feed two sections.
    """
    if mode not in QUOTA_MODES:
        return None
    asked = (prompt or "").casefold()
    text = " ".join([asked, *(p.subject for p in profiles)]).casefold()
    for exam in EXAMS:
        if mode == "full_mock" and re.search(exam.pattern, text):
            return exam
        if re.search(exam.pattern, asked) and _sections_fed(exam, profiles) >= 2:
            return exam
    return None


def _split(count: int, weights: Sequence[float]) -> list[int]:
    """Largest-remainder split of `count` by `weights` (sums to `count`)."""
    total = sum(weights) or 1.0
    raw = [count * w / total for w in weights]
    parts = [math.floor(r) for r in raw]
    order = sorted(range(len(raw)), key=lambda i: raw[i] - parts[i], reverse=True)
    for i in order[: count - sum(parts)]:
        parts[i] += 1
    return parts


def quotas(exam: Exam, count: int) -> tuple[DomainQuota, ...]:
    """Slots per domain: sections by weight, then domains within each section."""
    out: list[DomainQuota] = []
    sections = _split(count, [s.weight for s in exam.sections])
    for section, size in zip(exam.sections, sections, strict=True):
        sizes = _split(size, [d.weight for d in section.domains])
        out.extend(
            DomainQuota(
                d.name,
                section.name,
                n,
                section.modes,
                section.kinds,
                d.aliases,
                d.templates,
            )
            for d, n in zip(section.domains, sizes, strict=True)
            if n
        )
    return tuple(out)


def match_quota(domain: str, table: Sequence[DomainQuota]) -> DomainQuota | None:
    """The quota a planner's domain name belongs to, or None."""
    folded = domain.casefold()
    for quota in table:
        if quota.domain.casefold() == folded:
            return quota
    for quota in table:
        if any(alias in folded for alias in quota.aliases):
            return quota
    return None
