"""The blueprint: one spec per item, exact count, varied templates."""

import math
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, replace
from itertools import cycle
from typing import Any, Final

from app.modules.notebooks.domain.assessment.exams import DomainQuota, match_quota
from app.modules.notebooks.domain.assessment.modes import MODE_SPECS, ModeSpec
from app.modules.notebooks.domain.assessment.profile import SourceProfile

from pydantic import BaseModel, Field

PLAN_SCHEMA_NAME: Final = "nb_assessment_plan"
PLAN_MAX_TOKENS: Final = 3_000
PLAN_SLOT_TOKENS: Final = 70  # one planned slot as JSON (60 slots ~ 4 000 tokens)
MAX_TEMPLATE_SHARE: Final = 0.3
LEVELS: Final = ("easy", "medium", "hard")
TEXT_CHARS: Final = 80


@dataclass(frozen=True, slots=True)
class ItemSpec:
    """One planned item."""

    id: str
    type: str  # quiz: single | multiple | true_false; cards: "card"
    template: str
    domain: str
    difficulty: str
    source: str  # a source label such as "S1", or ""
    focus: str = ""  # the term, formula or problem to use, when the plan names one
    stimulus: bool = False  # the item must carry its own passage excerpt

    def as_dict(self) -> dict[str, Any]:
        """JSON-safe form."""
        return {
            "id": self.id,
            "type": self.type,
            "template": self.template,
            "domain": self.domain,
            "difficulty": self.difficulty,
            "source": self.source,
            "focus": self.focus,
            "stimulus": self.stimulus,
        }


class PlanItemOut(BaseModel):
    """A slot as the planning model writes it."""

    template: str
    domain: str
    difficulty: str
    source: str = Field(description='a source label such as "S1"')
    focus: str = Field(description="the term, formula or problem to test, or ''")


class PlanOut(BaseModel):
    """The planning model's JSON document."""

    items: list[PlanItemOut]


def plan_tokens(count: int) -> int:
    """`max_tokens` of the planning call: enough for every slot of a long set."""
    return max(PLAN_MAX_TOKENS, PLAN_SLOT_TOKENS * count + 500)


def template_cap(count: int, templates: int, share: float = MAX_TEMPLATE_SHARE) -> int:
    """Most items one template may take: the share, unless too few templates exist."""
    if templates <= 0:
        return count
    return max(math.ceil(count * share), math.ceil(count / templates))


def _domains(profiles: Sequence[SourceProfile]) -> list[tuple[str, str]]:
    pairs = [(d, p.label) for p in profiles for d in p.domains]
    if pairs:
        return pairs
    return [(p.subject or "general", p.label) for p in profiles] or [("general", "")]


def _clean(value: str) -> str:
    return " ".join(value.split())[:TEXT_CHARS]


@dataclass(frozen=True, slots=True)
class BlueprintRules:
    """What the blueprint must honour."""

    count: int
    types: tuple[str, ...]  # allowed item types, in preference order
    templates: tuple[str, ...]
    difficulty: str = "medium"
    stimulus: bool = False
    share: float = MAX_TEMPLATE_SHARE
    labels: frozenset[str] = frozenset()
    stimulus_templates: frozenset[str] = frozenset()  # empty: every template
    quotas: tuple[DomainQuota, ...] = ()  # an exam's slots per domain
    cards: bool = False

    def quota_templates(self, quota: DomainQuota) -> tuple[str, ...]:
        """The quota's own quiz templates, else those of its section modes."""
        if quota.templates and not self.cards:
            return quota.templates
        names = (
            t
            for mode in quota.modes
            for t in (
                MODE_SPECS[mode].card_templates
                if self.cards
                else MODE_SPECS[mode].quiz_templates
            )
        )
        return tuple(dict.fromkeys(names))

    def all_templates(self) -> tuple[str, ...]:
        """Every template a slot may take."""
        if not self.quotas:
            return self.templates
        names = (t for q in self.quotas for t in self.quota_templates(q))
        return tuple(dict.fromkeys(names))


Raw = tuple[str, str, str, str, str]  # template, domain, level, source, focus


def _type_for(rules: BlueprintRules, index: int) -> str:
    """Mostly the first type, every fourth item another one (when allowed)."""
    others = rules.types[1:]
    if others and index % 4 == 3:
        return others[(index // 4) % len(others)]
    return rules.types[0]


def _level(rules: BlueprintRules, index: int) -> str:
    """The requested level, with one easier and one harder in every five items."""
    base = LEVELS.index(rules.difficulty) if rules.difficulty in LEVELS else 1
    shift = {1: -1, 3: 1}.get(index % 5, 0)
    return LEVELS[min(max(base + shift, 0), len(LEVELS) - 1)]


def _needs_stimulus(rules: BlueprintRules, template: str) -> bool:
    """A stimulus slot: the mode needs one and the template reads a passage."""
    if not rules.stimulus:
        return False
    return not rules.stimulus_templates or template in rules.stimulus_templates


def _specs(rules: BlueprintRules, raw: Sequence[Raw]) -> list[ItemSpec]:
    return [
        ItemSpec(
            id=f"b{index + 1}",
            type=_type_for(rules, index),
            template=template,
            domain=domain,
            difficulty=level,
            source=source,
            focus=focus,
            stimulus=_needs_stimulus(rules, template),
        )
        for index, (template, domain, level, source, focus) in enumerate(raw)
    ]


def _source_for(quota: DomainQuota, profiles: Sequence[SourceProfile]) -> str:
    """A source that feeds the quota's section: by domain name, else by kind."""
    for profile in profiles:
        if any(match_quota(d, (quota,)) for d in profile.domains):
            return profile.label
    for profile in profiles:
        if profile.kind in quota.kinds:
            return profile.label
    return ""


def _quota_blueprint(
    rules: BlueprintRules,
    profiles: Sequence[SourceProfile],
    proposed: Sequence[PlanItemOut],
) -> list[ItemSpec]:
    """Exactly the exam's slots per domain; the planner's slots kept while they fit."""
    templates = rules.all_templates()
    cap = template_cap(rules.count, len(templates), rules.share)
    used: Counter[str] = Counter()
    left = {q.domain: q.count for q in rules.quotas}
    order = {q.domain: i for i, q in enumerate(rules.quotas)}
    raw: list[Raw] = []
    for slot in proposed:
        quota = match_quota(slot.domain, rules.quotas)
        template = slot.template.strip()
        if quota is None or not left[quota.domain] or used[template] >= cap:
            continue
        if template not in rules.quota_templates(quota):
            continue
        used[template] += 1
        left[quota.domain] -= 1
        level = slot.difficulty if slot.difficulty in LEVELS else rules.difficulty
        source = slot.source.strip() if slot.source.strip() in rules.labels else ""
        raw.append((template, quota.domain, level, source, _clean(slot.focus)))
    for quota in rules.quotas:
        own = rules.quota_templates(quota)
        source = _source_for(quota, profiles)
        for index in range(left[quota.domain]):
            free = [t for t in own if used[t] < cap] or list(own)
            template = free[index % len(free)]
            used[template] += 1
            level = _level(rules, len(raw))
            raw.append((template, quota.domain, level, source, ""))
    raw.sort(key=lambda item: order[item[1]])
    return _specs(rules, raw)


def build_blueprint(
    rules: BlueprintRules,
    profiles: Sequence[SourceProfile],
    proposed: Sequence[PlanItemOut] = (),
) -> list[ItemSpec]:
    """Exactly `rules.count` specs; no template above its cap.

    With exam quotas every domain gets exactly its share. Otherwise the planner's
    slots are kept in order while they fit (known template, cap not reached) and
    the rest is filled round-robin over templates and domains.
    """
    if rules.quotas:
        return _quota_blueprint(rules, profiles, proposed)
    cap = template_cap(rules.count, len(rules.templates), rules.share)
    used: Counter[str] = Counter()
    raw: list[Raw] = []
    for slot in proposed:
        template = slot.template.strip()
        if len(raw) >= rules.count or template not in rules.templates:
            continue
        if used[template] >= cap:
            continue
        used[template] += 1
        level = slot.difficulty if slot.difficulty in LEVELS else rules.difficulty
        source = slot.source.strip() if slot.source.strip() in rules.labels else ""
        raw.append((template, _clean(slot.domain), level, source, _clean(slot.focus)))
    domains = cycle(_domains(profiles))
    templates = cycle(rules.templates)
    while len(raw) < rules.count:
        template = next(templates)
        if used[template] >= cap:
            continue
        used[template] += 1
        domain, source = next(domains)
        raw.append((template, _clean(domain), _level(rules, len(raw)), source, ""))
    return _specs(rules, raw)


def swap_template(rules: BlueprintRules, spec: ItemSpec) -> ItemSpec | None:
    """The slot with another template allowed in its domain, or None."""
    quota = match_quota(spec.domain, rules.quotas) if rules.quotas else None
    allowed = rules.quota_templates(quota) if quota else rules.templates
    if spec.template not in allowed:
        others = list(allowed)
    else:
        at = allowed.index(spec.template)
        others = list(allowed[at + 1 :] + allowed[:at])
    if not others:
        return None
    template = others[0]
    return replace(
        spec,
        template=template,
        focus="",
        stimulus=_needs_stimulus(rules, template),
    )


def rules_for(
    *,
    count: int,
    types: Sequence[str],
    spec: ModeSpec,
    cards: bool,
    difficulty: str,
    labels: Sequence[str],
    single_template: bool = False,
    quotas: tuple[DomainQuota, ...] = (),
) -> BlueprintRules:
    """The blueprint rules of a quiz or a card set in a mode.

    With exam quotas the passage templates of the sections' modes need a stimulus.
    """
    templates = spec.card_templates if cards else spec.quiz_templates
    stimulus, passages = spec.needs_stimulus, spec.stimulus_templates
    if quotas:
        reading = [
            t
            for q in quotas
            if any(MODE_SPECS[m].needs_stimulus for m in q.modes)
            for t in q.templates
            + tuple(t for m in q.modes for t in MODE_SPECS[m].quiz_templates)
        ]
        stimulus, passages = bool(reading), frozenset(reading)
    return BlueprintRules(
        count=count,
        types=tuple(types) or ("single",),
        templates=templates,
        difficulty=difficulty,
        stimulus=stimulus and not cards,
        share=1.0 if single_template else MAX_TEMPLATE_SHARE,
        labels=frozenset(labels),
        stimulus_templates=passages,
        quotas=quotas,
        cards=cards,
    )


def plan_message(
    rules: BlueprintRules,
    mode: str,
    profiles: Sequence[SourceProfile],
    prompt: str | None,
) -> str:
    """The planning call's task (the sources are in the first message)."""
    lines = "\n".join(
        f"- {p.label}: {p.kind}, {p.subject}; domains: {', '.join(p.domains)}"
        for p in profiles
    )
    focus = f"\nThe student asked: {prompt}" if prompt else ""
    if rules.quotas:
        focus += "\nUse exactly these domains and slot counts: " + "; ".join(
            f"{q.domain} ({q.section}): {q.count}, templates "
            f"{', '.join(rules.quota_templates(q))}"
            for q in rules.quotas
        )
    return (
        f"Plan a {mode.replace('_', ' ')} of exactly {rules.count} items before "
        "they are written. Return one slot per item with: template (one of "
        f"{', '.join(rules.all_templates())}), domain (a unit or skill area of the "
        "sources), difficulty (easy, medium or hard), source (the label the item "
        "draws on) and focus (the exact term, formula or problem to use, or ''). "
        f"No template may take more than {round(rules.share * 100)}% of the items. "
        "Spread the slots over the domains in proportion to their weight (for an "
        "exam, follow its official section weights); never repeat a focus. When "
        "the sources prepare one exam, weight the exam's sections, not the "
        "sources: a word list only feeds the vocabulary skill of its section.\n"
        f"Sources:\n{lines}{focus}"
    )


PLAN_SYSTEM: Final = (
    "You are an assessment designer. You plan tests and flash card sets slot by "
    "slot. Answer only with the JSON document."
)
