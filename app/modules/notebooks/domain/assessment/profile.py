"""Source profiles: what each selected source is and which items it can feed."""

import re
from dataclasses import dataclass, field
from typing import Any, Final, Literal

from pydantic import BaseModel, Field

SourceKind = Literal[
    "vocabulary_list",
    "problem_set",
    "formula_sheet",
    "reading_passages",
    "textbook_chapter",
    "lecture_notes",
    "exam_paper",
    "other",
]
SOURCE_KINDS: Final[tuple[str, ...]] = (
    "vocabulary_list",
    "problem_set",
    "formula_sheet",
    "reading_passages",
    "textbook_chapter",
    "lecture_notes",
    "exam_paper",
    "other",
)
PROFILE_SCHEMA_NAME: Final = "nb_source_profile"
PROFILE_MAX_TOKENS: Final = 1_200
SAMPLE_CHARS: Final = 4_000  # per source: the profile reads the beginning only
LIST_MAX: Final = 8
TEXT_CHARS: Final = 80

# "erratic - unpredictable", "erratic: unpredictable", "erratic — ..."
_GLOSS_LINE: Final = re.compile(r"^\s*[\w'’ -]{2,40}\s*(?:[-–—:=]|\(\w+\.?\))\s*\S")
_MATH: Final = re.compile(r"\$[^$]+\$|\\frac|\\sqrt|[0-9]\s*[=<>+*/^]\s*[0-9a-z(]")
_PROBLEM: Final = re.compile(r"(?im)^\s*(?:\d{1,3}[.)]|problem|задача|masala)\b")


class SourceProfileOut(BaseModel):
    """One source as the profiling model describes it."""

    label: str = Field(description='the source label, e.g. "S1"')
    kind: SourceKind
    subject: str = Field(description="e.g. SAT Math, English vocabulary, Biology")
    domains: list[str] = Field(description="up to 8 domains or units covered")
    item_pools: list[str] = Field(
        description="up to 8 usable pools: terms, problems, formulas, passages..."
    )
    has_math: bool
    term_definition_pairs: bool


class ProfilesOut(BaseModel):
    """The profiling model's JSON document."""

    sources: list[SourceProfileOut]


@dataclass(frozen=True, slots=True)
class SourceProfile:
    """What a source is, cleaned."""

    label: str
    kind: str
    subject: str = ""
    domains: list[str] = field(default_factory=list)
    item_pools: list[str] = field(default_factory=list)
    has_math: bool = False
    term_definition_pairs: bool = False

    def as_dict(self) -> dict[str, Any]:
        """JSON-safe form (stored with the blueprint)."""
        return {
            "label": self.label,
            "kind": self.kind,
            "subject": self.subject,
            "domains": list(self.domains),
            "item_pools": list(self.item_pools),
            "has_math": self.has_math,
            "term_definition_pairs": self.term_definition_pairs,
        }


def _short(values: list[str]) -> list[str]:
    cleaned = [" ".join(str(v).split())[:TEXT_CHARS] for v in values]
    return list(dict.fromkeys(v for v in cleaned if v))[:LIST_MAX]


def clean_profiles(data: dict[str, Any], labels: list[str]) -> list[SourceProfile]:
    """Valid profiles of known labels; unknown labels and bad rows are dropped."""
    try:
        parsed = ProfilesOut.model_validate(data)
    except ValueError:
        return []
    known = set(labels)
    profiles: dict[str, SourceProfile] = {}
    for row in parsed.sources:
        label = row.label.strip()
        if label in known and label not in profiles:
            profiles[label] = SourceProfile(
                label=label,
                kind=row.kind,
                subject=" ".join(row.subject.split())[:TEXT_CHARS],
                domains=_short(row.domains),
                item_pools=_short(row.item_pools),
                has_math=row.has_math,
                term_definition_pairs=row.term_definition_pairs,
            )
    return list(profiles.values())


def guess_profile(label: str, text: str) -> SourceProfile:
    """A rule-based profile when the model is unavailable."""
    lines = [line for line in text.splitlines() if line.strip()]
    glossy = sum(1 for line in lines if _GLOSS_LINE.match(line))
    has_math = len(_MATH.findall(text)) >= 3
    if lines and glossy / len(lines) >= 0.5:
        kind = "vocabulary_list"
    elif has_math and len(_PROBLEM.findall(text)) >= 3:
        kind = "problem_set"
    else:
        kind = "other"
    return SourceProfile(
        label=label,
        kind=kind,
        has_math=has_math,
        term_definition_pairs=kind == "vocabulary_list",
    )


def profile_message(samples: dict[str, str]) -> str:
    """The user message of the profiling call: the beginning of each source."""
    blocks = "\n\n".join(
        f'<source id="{label}">\n{text[:SAMPLE_CHARS]}\n</source>'
        for label, text in samples.items()
    )
    return (
        "Classify each source below for building a test or flash cards.\n"
        f"kind is one of: {', '.join(SOURCE_KINDS)}. A list of words with "
        "definitions is vocabulary_list; numbered exercises are problem_set; "
        "texts students read and answer questions about are reading_passages. "
        "subject names the subject and exam if any (e.g. 'SAT Reading and "
        "Writing'). domains are the units or skill areas covered. item_pools "
        "name what items can be built from (e.g. '120 words with definitions', "
        "'linear equations problems'). Return one row per source with its id "
        "as label.\n\n"
        f"{blocks}"
    )


PROFILE_SYSTEM: Final = (
    "You profile study materials. Answer only with the JSON document; be brief."
)
