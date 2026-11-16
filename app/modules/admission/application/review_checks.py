"""Post-validation of item outputs (§9.3) and the review cache key (§9.4)."""

import hashlib
import json
import re
import unicodedata
from collections.abc import Iterable, Sequence
from decimal import Decimal, InvalidOperation
from typing import Any, Final

from app.modules.admission.application.review_schema import AiRewrite, AiWordFit
from app.modules.admission.domain.items import (
    DESCRIPTION_MAX,
    HONOR_DESCRIPTION_MAX,
    ORG_MAX,
    TITLE_MAX,
    Item,
)
from app.modules.admission.ports.items import Metric

_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_URL = re.compile(r"(?:https?://|www\.)\S+", re.IGNORECASE)
_MARKS = re.compile(r"[*_`#>|~]+")
_NUMBER = re.compile(r"\d+(?:[.,\u00a0 ]\d{3})*(?:[.,]\d+)?")
_INJECTION = re.compile(
    r"ignore (?:all |any )?(?:previous|prior|above) instructions|system prompt|"
    r"you are now|give (?:me|this) (?:an? )?A\b|игнорируй|забудь (?:все )?инструкц|"
    r"oldingi ko.rsatmalarni",
    re.IGNORECASE,
)

FUTURE_MARKERS: Final[tuple[str, ...]] = (
    # en
    "will",
    "aim",
    "plan",
    "goal",
    "by ",
    # ru
    "планир",
    "цель",
    "стремл",
    "к ",
    "до ",
    # uz
    "reja",
    "maqsad",
    "gacha",
    "moqchi",
)
"""Words that mark a sentence about a plan; a projected number needs one."""


def nfc(text: str) -> str:
    """Return the NFC form."""
    return unicodedata.normalize("NFC", text)


def plain(text: str) -> str:
    """Strip Markdown and links from model text."""
    text = _LINK.sub(r"\1", text)
    text = _URL.sub("", text)
    text = _MARKS.sub("", text)
    return re.sub(r"\s+", " ", nfc(text)).strip()


def limits_for(kind: str) -> tuple[int, int, int]:
    """Return the position, organization and description caps of an item kind."""
    description = HONOR_DESCRIPTION_MAX if kind == "honor" else DESCRIPTION_MAX
    return TITLE_MAX, ORG_MAX, description


def numbers(text: str) -> set[Decimal]:
    """Return the numbers written in a text ("1,000", "1 000" and "1000" are equal)."""
    found: set[Decimal] = set()
    for raw in _NUMBER.findall(text):
        found.add(_number(raw))
    return {n for n in found if n.is_finite()}


def _number(raw: str) -> Decimal:
    cleaned = raw.replace("\u00a0", "").replace(" ", "")
    if re.fullmatch(r"\d{1,3}(?:[.,]\d{3})+", cleaned):
        cleaned = re.sub(r"[.,]", "", cleaned)
    else:
        cleaned = cleaned.replace(",", ".")
    try:
        return Decimal(cleaned).normalize()
    except InvalidOperation:
        return Decimal("NaN")


def item_numbers(item: Item) -> set[Decimal]:
    """Return every number the student stated on the item itself."""
    text = " ".join([item.title, item.organization, item.description])
    stated = numbers(text)
    for value in (item.hours_per_week, item.weeks_per_year, *item.grades):
        if value is not None:
            stated.add(Decimal(value).normalize())
    return stated


def _metric_numbers(metric: Metric) -> set[Decimal]:
    found = {metric.value.normalize()}
    if metric.target_date is not None:
        found |= {Decimal(metric.target_date.year), Decimal(metric.target_date.day)}
    return found


def rewrite_violation(
    rewrite: AiRewrite, item: Item, metrics: Sequence[Metric]
) -> str | None:
    """Return why a rewrite breaks the rules, or None when it is acceptable."""
    position_max, org_max, description_max = limits_for(item.kind)
    for value, cap, name in (
        (rewrite.position, position_max, "position"),
        (rewrite.org, org_max, "organization"),
        (rewrite.description, description_max, "description"),
    ):
        if len(nfc(value)) > cap:
            return f"the {name} is longer than {cap} characters"
    by_id = {str(m.id): m for m in metrics}
    current: set[Decimal] = set(item_numbers(item))
    projected: set[Decimal] = set()
    for metric in metrics:
        (current if metric.horizon == "current" else projected).update(
            _metric_numbers(metric)
        )
    projected -= current
    text = " ".join([rewrite.position, rewrite.org, rewrite.description])
    used = numbers(text)
    unknown = used - current - projected
    if unknown:
        return "it uses numbers the student did not state: " + ", ".join(
            sorted(str(n) for n in unknown)
        )
    projected_used = used & projected
    if projected_used:
        refs = {r.metric_id for r in rewrite.claim_refs if r.horizon == "projected"}
        cited = set().union(*(_metric_numbers(by_id[r]) for r in refs if r in by_id))
        if not projected_used <= cited:
            return "a planned number is not cited as projected in claim_refs"
        lowered = text.casefold()
        if not any(marker in lowered for marker in FUTURE_MARKERS):
            return "a planned number is written as if it were already achieved"
    return None


def clean_rewrite(rewrite: AiRewrite, metrics: Sequence[Metric]) -> AiRewrite:
    """Return the rewrite as plain text with unknown metric refs dropped."""
    ids = {str(m.id): m.horizon for m in metrics}
    refs = [r for r in rewrite.claim_refs if ids.get(r.metric_id) == r.horizon]
    return AiRewrite(
        position=plain(rewrite.position),
        org=plain(rewrite.org),
        description=plain(rewrite.description),
        claim_refs=refs,
    )


def projected_only_numbers(item: Item, metrics: Sequence[Metric]) -> set[Decimal]:
    """Return the numbers that exist only as plans."""
    current = set(item_numbers(item))
    projected: set[Decimal] = set()
    for metric in metrics:
        if metric.horizon == "current":
            current.add(metric.value.normalize())
        else:
            projected.add(metric.value.normalize())
    return projected - current


def align_word_fit(fits: Iterable[AiWordFit], words: Sequence[str]) -> list[AiWordFit]:
    """Return exactly one fit per student word in the student's order."""
    by_word = {nfc(f.word).casefold(): f for f in fits}
    aligned: list[AiWordFit] = []
    for word in words:
        got = by_word.get(nfc(word).casefold())
        aligned.append(
            AiWordFit(word=word, fit=got.fit, evidence=plain(got.evidence))
            if got
            else AiWordFit(word=word, fit="none", evidence="")
        )
    return aligned


def looks_injected(item: Item) -> bool:
    """Return whether the item text tries to give the model instructions."""
    text = " ".join([item.title, item.organization, item.description])
    return bool(_INJECTION.search(text))


def delimit(item: Item, metrics: Sequence[Metric], *, strict: bool) -> str:
    """Return the item as untrusted data; strict mode escapes the delimiters."""

    def neutral(text: str) -> str:
        text = text.replace("<", "‹").replace(">", "›")
        return text.replace("```", "'''") if strict else text

    lines = [
        f"kind: {item.kind}",
        f"position: {neutral(item.title)}",
        f"organization: {neutral(item.organization)}",
        f"description: {neutral(item.description)}",
        f"category: {neutral(item.category or '')}",
        f"grades: {', '.join(str(g) for g in item.grades)}",
        f"hours_per_week: {item.hours_per_week or ''}",
        f"weeks_per_year: {item.weeks_per_year or ''}",
    ]
    for m in metrics:
        when = f"target {m.target_date}" if m.horizon == "projected" else "current"
        unit = f" {neutral(m.unit)}" if m.unit else ""
        lines.append(
            f"metric {m.id}: {neutral(m.label)} = {m.value}{unit} ({when}, "
            f"{m.provenance})"
        )
    body = "\n".join(lines)
    return f"<item>\n{body}\n</item>"


def canonical_metrics(metrics: Sequence[Metric]) -> list[dict[str, Any]]:
    """Return the metrics in a stable, comparable form."""
    return sorted(
        (
            {
                "id": str(m.id),
                "label": nfc(m.label),
                "value": str(m.value.normalize()),
                "unit": m.unit,
                "horizon": m.horizon,
                "as_of": m.as_of.isoformat() if m.as_of else None,
                "target_date": m.target_date.isoformat() if m.target_date else None,
                "provenance": m.provenance,
            }
            for m in metrics
        ),
        key=lambda m: m["id"],
    )


def input_hash(fields: dict[str, Any]) -> str:
    """Return the sha256 of the canonical JSON of the review inputs."""
    blob = json.dumps(fields, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(blob.encode()).hexdigest()
