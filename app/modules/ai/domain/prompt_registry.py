"""Editable prompts: built-in slots, stored versions and how an override applies.

A slot is one named piece of a task's instructions (`task`, `name`) with a built-in
text. The built-in may be a template with `{placeholders}` that the builder fills
(the answer language, the date, a limit). An administrator stores a new version of a
slot, for all locales (`locale` ""), or for one; one version per slot and locale is
active. The text that reaches the model is the active version, else the built-in.

Builders keep producing their built-in text; the recording gateway finds each slot
of the call's task in the system prompt and puts the active version in its place
(placeholders keep the values the builder put there). `apply_overrides` is that
step; it never sees anything but the system prompt and the slots.
"""

import hashlib
import re
from collections.abc import Iterable, Mapping, Sequence
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime
from functools import lru_cache
from string import Formatter
from uuid import UUID

ALL_LOCALES = ""  # an override that applies whatever the locale
LOCALES: tuple[str, ...] = ("uz", "ru", "en")
BUILT_IN_VERSION = 0
MAX_PROMPT_CHARS = 50_000
HASH_CHARS = 16


def prompt_hash(text: str) -> str:
    """A short, stable fingerprint of a prompt text (never the text itself)."""
    return hashlib.sha256(text.encode()).hexdigest()[:HASH_CHARS]


def fields_of(template: str) -> frozenset[str]:
    """The placeholder names of a template (`{name}`; `{{` is a literal brace)."""
    try:
        return frozenset(
            name for _, name, _, _ in Formatter().parse(template) if name is not None
        )
    except ValueError:
        return frozenset({"<invalid>"})


@dataclass(frozen=True, slots=True)
class PromptSlot:
    """A built-in piece of a task's prompt that administrators may replace.

    `template` True: `builtin` has `{placeholders}` the builder fills; an override
    may use the same placeholders and no others. False: `builtin` is literal text.
    """

    task: str
    name: str
    summary: str
    builtin: str
    template: bool = False

    @property
    def key(self) -> tuple[str, str]:
        """(task, name)."""
        return (self.task, self.name)

    @property
    def fields(self) -> frozenset[str]:
        """The placeholders the builder fills."""
        return fields_of(self.builtin) if self.template else frozenset()

    @property
    def pattern(self) -> re.Pattern[str] | None:
        """A regex that finds the filled built-in in a prompt (templates only)."""
        return _compile(self.builtin) if self.template else None


@lru_cache(maxsize=512)
def _compile(builtin: str) -> re.Pattern[str]:
    """A regex finding the filled template; placeholders match lazily."""
    parts: list[str] = []
    seen: set[str] = set()
    tokens = list(Formatter().parse(builtin))
    for index, (literal, name, _, _) in enumerate(tokens):
        parts.append(re.escape(literal))
        if name is None:
            continue
        group = _group(name)
        if group in seen:
            parts.append(f"(?P={group})")
            continue
        seen.add(group)
        # a trailing placeholder has no literal after it: take the rest of the line
        body = r"[^\n]*" if index == len(tokens) - 1 else ".*?"
        parts.append(f"(?P<{group}>{body})")
    return re.compile("".join(parts), re.DOTALL)


def _group(name: str) -> str:
    return "f_" + re.sub(r"\W", "_", name)


@dataclass(frozen=True, slots=True)
class PromptVersion:
    """A stored text of a slot for a locale ("" = all); one per slot+locale is active.

    Versions are numbered per task, so a task's calls can be compared by version.
    """

    id: UUID
    task: str
    name: str
    locale: str
    version: int
    text: str
    hash: str
    active: bool
    created_at: datetime
    created_by: UUID | None = None
    note: str = ""


@dataclass(frozen=True, slots=True)
class ResolvedPrompt:
    """The text a builder should use, with its version (0 built-in) and hash."""

    text: str
    version: int
    hash: str


@dataclass(frozen=True, slots=True)
class PromptRef:
    """What a model call used: the task, the highest applied version and a hash.

    The hash covers every applied version, so two calls with the same version but a
    different mix of rolled-back slots are still told apart.
    """

    task: str
    version: int
    hash: str | None


@dataclass(frozen=True, slots=True)
class ActiveOverrides:
    """The active versions of every slot, by (task, name) then locale."""

    by_slot: Mapping[tuple[str, str], Mapping[str, PromptVersion]] = field(
        default_factory=dict
    )

    @classmethod
    def of(cls, versions: Iterable[PromptVersion]) -> "ActiveOverrides":
        """Index the active versions."""
        index: dict[tuple[str, str], dict[str, PromptVersion]] = {}
        for item in versions:
            if item.active:
                index.setdefault((item.task, item.name), {})[item.locale] = item
        return cls(index)

    def get(self, task: str, name: str, locale: str) -> PromptVersion | None:
        """The version for the locale, else the all-locales one, else None."""
        per_locale = self.by_slot.get((task, name))
        if not per_locale:
            return None
        return per_locale.get(locale) or per_locale.get(ALL_LOCALES)

    def has_task(self, task: str) -> bool:
        """Whether any slot of the task is overridden."""
        return any(key[0] == task for key in self.by_slot)


def resolve(
    slot: PromptSlot | None,
    active: ActiveOverrides,
    task: str,
    name: str,
    locale: str,
    default: str | None = None,
) -> ResolvedPrompt:
    """The active version of a slot, else its built-in text (or `default`)."""
    found = active.get(task, name, locale)
    if found is not None:
        return ResolvedPrompt(found.text, found.version, found.hash)
    text = default if default is not None else (slot.builtin if slot else "")
    return ResolvedPrompt(text, BUILT_IN_VERSION, prompt_hash(text))


def apply_overrides(
    system: str,
    task: str,
    slots: Sequence[PromptSlot],
    active: ActiveOverrides,
    locale: str = ALL_LOCALES,
) -> tuple[str, PromptRef | None]:
    """Put the active versions of the task's slots in place of their built-ins.

    Returns the new system prompt and the reference of what was applied (None when
    no override of the task was found in the prompt).
    """
    applied: list[PromptVersion] = []
    for slot in slots:
        found = active.get(task, slot.name, locale)
        if found is None:
            continue
        replaced = _replace(system, slot, found.text)
        if replaced is not None:
            system = replaced
            applied.append(found)
    if not applied:
        return system, None
    joined = "|".join(f"{v.name}:{v.locale}:{v.version}:{v.hash}" for v in applied)
    top = max(v.version for v in applied)
    return system, PromptRef(task, top, prompt_hash(joined))


def _replace(system: str, slot: PromptSlot, text: str) -> str | None:
    pattern = slot.pattern
    if pattern is None:
        if slot.builtin not in system:
            return None
        return system.replace(slot.builtin, text, 1)
    match = pattern.search(system)
    if match is None:
        return None
    values = {name: match.group(_group(name)) for name in slot.fields}
    try:
        filled = text.format(**values)
    except (KeyError, IndexError, ValueError):
        return None
    return system[: match.start()] + filled + system[match.end() :]


def check_override(slot: PromptSlot, text: str) -> str | None:
    """Why a text cannot replace the slot (None when it can)."""
    if not text.strip():
        return "empty"
    if len(text) > MAX_PROMPT_CHARS:
        return "too_long"
    if slot.template:
        extra = fields_of(text) - slot.fields
        if extra:
            return "unknown_placeholder"
    return None


_LAST_PROMPT: ContextVar[PromptRef | None] = ContextVar("ai_last_prompt", default=None)


def note_prompt(ref: PromptRef | None) -> None:
    """Remember the prompt the current request's latest model call used."""
    _LAST_PROMPT.set(ref)


def last_prompt() -> PromptRef | None:
    """The prompt the current request's latest model call used (None: none yet)."""
    return _LAST_PROMPT.get()
