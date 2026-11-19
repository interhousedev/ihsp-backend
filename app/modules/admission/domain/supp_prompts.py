"""Supplemental essay prompts of an institution per admission cycle."""

import re
from dataclasses import dataclass
from typing import Final, Literal

CYCLE_RE: Final = re.compile(r"^(\d{4})-(\d{2})$")
MAX_PROMPTS: Final = 30
MAX_PROMPT_LEN: Final = 4000
MAX_URL_LEN: Final = 500
MAX_WORD_LIMIT: Final = 5000
MAX_PROPOSED_PROMPTS: Final = 12
"""Most supplement prompts one catalog proposal carries."""

PromptStatus = Literal["new", "changed", "same", "removed"]


@dataclass(frozen=True, slots=True)
class SuppPrompt:
    """One prompt as published for a cycle."""

    position: int
    prompt: str
    word_limit: int | None
    required: bool
    source_url: str | None


@dataclass(frozen=True, slots=True)
class PromptChange:
    """A prompt of a cycle compared with the previous cycle."""

    prompt: SuppPrompt
    status: PromptStatus
    previous_text: str | None


@dataclass(frozen=True, slots=True)
class CyclePrompts:
    """The prompts of one cycle with their change status."""

    cycle: str
    prompts: tuple[PromptChange, ...]


def valid_cycle(cycle: str) -> bool:
    """`YYYY-YY` with consecutive years, e.g. `2025-26`."""
    m = CYCLE_RE.match(cycle)
    if m is None:
        return False
    start = int(m.group(1))
    return (start + 1) % 100 == int(m.group(2))


def previous_cycle(cycle: str) -> str:
    """The cycle one year earlier: `2025-26` gives `2024-25`."""
    start = int(cycle[:4]) - 1
    return f"{start}-{(start + 1) % 100:02d}"


def normalize(text: str) -> str:
    """Lower-case words without punctuation, quotes or extra spaces."""
    return " ".join(re.sub(r"[^\w\s]", " ", text.casefold()).split())


def diff_cycle(
    current: list[SuppPrompt], previous: list[SuppPrompt] | None
) -> tuple[PromptChange, ...]:
    """Mark each prompt new, changed or same; append removed ones.

    Without a previous cycle every prompt is `new`. A prompt whose
    normalized text appears last year is `same`; otherwise a prompt at the
    same position whose text differs is `changed` (with the old text).
    """
    if previous is None:
        return tuple(PromptChange(p, "new", None) for p in current)
    old_by_text = {normalize(p.prompt): p for p in previous}
    used: set[int] = set()
    out: list[PromptChange] = []
    for p in current:
        match = old_by_text.get(normalize(p.prompt))
        if match is not None and match.position not in used:
            used.add(match.position)
            out.append(PromptChange(p, "same", None))
        else:
            out.append(PromptChange(p, "new", None))
    old_by_pos = {p.position: p for p in previous}
    for i, change in enumerate(out):
        if change.status != "new":
            continue
        old = old_by_pos.get(change.prompt.position)
        if old is not None and old.position not in used:
            used.add(old.position)
            out[i] = PromptChange(change.prompt, "changed", old.prompt)
    out.extend(
        PromptChange(p, "removed", None) for p in previous if p.position not in used
    )
    return tuple(out)


def history(by_cycle: dict[str, list[SuppPrompt]]) -> list[CyclePrompts]:
    """Cycles newest first, each compared with the cycle before it."""
    return [
        CyclePrompts(
            cycle=c,
            prompts=diff_cycle(by_cycle[c], by_cycle.get(previous_cycle(c))),
        )
        for c in sorted(by_cycle, reverse=True)
    ]
