"""Model calls that read an essay: check, feedback, base and university reviews.

Pure functions over the `StructuredAi` and `PromptSource` ports: no quota, no
access check, no storage. The coach and the review service gate them.
"""

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from typing import Any, Final
from uuid import UUID

from app.modules.admission.application.review_checks import nfc
from app.modules.admission.application.words import delimit, plain
from app.modules.admission.domain.essay_reviews import (
    ALIGNMENTS,
    MAX_LIST,
    AoReaction,
    BaseReview,
    DimensionScore,
    EssayInput,
    ExemplarPattern,
    GoalAlignment,
    ParagraphNote,
    UniContext,
    UniGoal,
    UniReview,
)
from app.modules.admission.domain.essay_text import paragraphs as essay_paragraphs
from app.modules.admission.domain.essays import Essay, word_count
from app.modules.admission.domain.exemplars import ExemplarMatch
from app.modules.admission.infrastructure.ai.prompts import essay_review as review
from app.modules.admission.infrastructure.ai.prompts import essays as prompt
from app.modules.admission.ports.ai import PromptSource, StructuredAi
from app.modules.admission.ports.unit_of_work import AdmissionUnitOfWork
from app.shared.ai_tasks import AiTask
from app.shared.brand import with_brand
from app.shared.contracts.ai import AiProviderError

CHECK_MAX_SCORE: Final = 5
CHECK_GENERIC_DIMS: Final = 3
CHECK_BANDS: Final = (
    (85, "exceptional"),
    (60, "strong"),
    (35, "solid"),
    (15, "developing"),
    (0, "weak"),
)
GOAL_FACTS: Final = ("mission", "admission_values")
_CHECK_TOKENS: Final = 3000
_TOKENS: Final = 1200
_REVIEW_TOKENS: Final = 3000
_FLAGGED_MAX: Final = 1200
_BODY_TO_MODEL: Final = 12000
_EXEMPLAR_TO_MODEL: Final = 4000


@dataclass(frozen=True, slots=True)
class SentenceNote:
    """A comment on one sentence."""

    quote: str
    comment: str


@dataclass(frozen=True)
class Feedback:
    """Comments on a draft; never replacement text."""

    summary: str
    strengths: list[str]
    suggestions: list[str]
    word_count: int
    word_limit: int | None
    sentences: list[SentenceNote] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class CheckDimension:
    """One scored rubric dimension; the quote is verified against the essay."""

    dim: str
    score: int
    quote: str | None
    comment: str


@dataclass(frozen=True, slots=True)
class EssayCheck:
    """An essay scored against its prompt and the rubric."""

    score: int
    band: str
    dimensions: list[CheckDimension]
    prompt_fit: str
    prompt_fit_reason: str
    strongest: str
    first_fix: str
    flagged_paragraph: int | None
    flagged_text: str | None
    flagged_reason: str
    summary: str
    word_count: int
    word_limit: int | None
    over_limit: bool
    generic: bool


def _get(obj: Any, key: str) -> Any:
    return obj.get(key) if isinstance(obj, Mapping) else getattr(obj, key, None)


def _flat(text: str) -> str:
    """NFC with every whitespace run collapsed, for verbatim comparison."""
    return " ".join(nfc(text).split())


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _line(value: Any) -> str:
    return nfc(plain(str(value or ""))).strip()[: prompt.LINE_MAX]


def _lines(values: Any, limit: int) -> list[str]:
    out: list[str] = []
    for raw in values or ():
        line = _line(raw)
        if line and line not in out:
            out.append(line)
    return out[:limit]


def _summary(value: Any) -> str:
    return nfc(plain(str(value or ""))).strip()[: prompt.SUMMARY_MAX]


def _verbatim(value: Any, haystack: str) -> str | None:
    """The quote when it occurs in the flattened essay, else None."""
    quote = _flat(str(value or ""))[: prompt.QUOTE_MAX]
    return quote if quote and quote in haystack else None


def _paragraphs(body: str) -> list[str]:
    return essay_paragraphs(body)


def band_of(score: int) -> str:
    """Name the band of a 0-100 score."""
    for floor, name in CHECK_BANDS:
        if score >= floor:
            return name
    return CHECK_BANDS[-1][1]


def essay_input(essay: Essay) -> EssayInput:
    """The parts of an essay a review reads."""
    return EssayInput(
        kind=essay.kind,
        title=essay.title,
        prompt_text=essay.prompt_text,
        word_limit=essay.word_limit,
        body=essay.body,
    )


def brief(essay: EssayInput) -> list[str]:
    """The brief lines of an essay: kind, title, prompt and word limit."""
    lines = [f"Essay kind: {essay.kind}"]
    if essay.title:
        lines.append(f"Title: {essay.title}")
    if essay.prompt_text:
        lines.append(f"Prompt: {essay.prompt_text}")
    if essay.word_limit:
        lines.append(f"Word limit: {essay.word_limit}")
    return lines


async def _ask(
    ai: StructuredAi,
    prompts: PromptSource,
    *,
    task: AiTask,
    name: str,
    schema: tuple[str, dict[str, Any]],
    locale: str,
    lines: Sequence[str],
    max_tokens: int,
) -> tuple[dict[str, Any], str]:
    return await ai.json(
        task=task,
        system=with_brand(await prompts.text(task, name, locale)),
        user=delimit([f"Language: {locale}", *lines]),
        schema_name=schema[0],
        schema=schema[1],
        max_tokens=max_tokens,
    )


def _checked(
    data: dict[str, Any],
    body: str,
    count: int,
    limit: int | None,
    has_prompt: bool,
) -> EssayCheck:
    """Turn the model's reply into a check the code can stand behind."""
    haystack = _flat(body)
    given: dict[str, Any] = {}
    for raw in data.get("dimensions") or []:
        dim = _get(raw, "dim")
        if dim in prompt.DIMENSIONS and dim not in given:
            given[dim] = raw
    dims: list[CheckDimension] = []
    for name in prompt.DIMENSIONS:
        raw = given.get(name)
        if raw is None:
            dims.append(CheckDimension(name, 0, None, ""))
            continue
        dims.append(
            CheckDimension(
                name,
                min(max(_int(_get(raw, "score")), 0), CHECK_MAX_SCORE),
                _verbatim(_get(raw, "quote"), haystack),
                _line(_get(raw, "comment")),
            )
        )
    total = sum(d.score for d in dims)
    score = round(total * 100 / (CHECK_MAX_SCORE * len(dims)))
    fit = data.get("prompt_fit")
    if not has_prompt:
        fit, reason = "unknown", ""
    else:
        fit = fit if fit in prompt.PROMPT_FITS else "partial"
        reason = _line(data.get("prompt_fit_reason"))
    strongest = data.get("strongest")
    if strongest not in prompt.DIMENSIONS:
        strongest = max(dims, key=lambda d: d.score).dim
    paragraphs = _paragraphs(body)
    index: int | None = None
    text: str | None = None
    if paragraphs:
        index = min(max(_int(data.get("flagged_paragraph")), 0), len(paragraphs) - 1)
        text = _flat(paragraphs[index])[:_FLAGGED_MAX]
    return EssayCheck(
        score=score,
        band=band_of(score),
        dimensions=dims,
        prompt_fit=fit,
        prompt_fit_reason=reason,
        strongest=strongest,
        first_fix=_line(data.get("first_fix")),
        flagged_paragraph=index,
        flagged_text=text,
        flagged_reason=_line(data.get("flagged_reason")),
        summary=_summary(data.get("summary")),
        word_count=count,
        word_limit=limit,
        over_limit=limit is not None and count > limit,
        generic=sum(1 for d in dims if d.score <= 1) >= CHECK_GENERIC_DIMS,
    )


async def run_check(
    ai: StructuredAi,
    prompts: PromptSource,
    *,
    essay: EssayInput,
    locale: str,
) -> tuple[EssayCheck, str]:
    """Score the essay on the six coach dimensions; returns the check and model."""
    count = word_count(essay.body)
    has_prompt = bool(essay.prompt_text.strip())
    lines = brief(essay) + [
        f"Word count: {count}",
        f"Essay: {essay.body[:_BODY_TO_MODEL]}",
    ]
    if not has_prompt:
        lines.insert(1, "Prompt: none given")
    data, model = await _ask(
        ai,
        prompts,
        task=AiTask.ADMIT_ESSAY_COACH,
        name="check",
        schema=prompt.SCHEMAS["check"],
        locale=locale,
        lines=lines,
        max_tokens=_CHECK_TOKENS,
    )
    check = _checked(data, essay.body, count, essay.word_limit, has_prompt)
    return check, model


async def run_feedback(
    ai: StructuredAi,
    prompts: PromptSource,
    *,
    essay: EssayInput,
    locale: str,
    context: Sequence[str] = (),
) -> tuple[Feedback, str]:
    """Comment on the draft; `context` adds the student's own related data."""
    count = word_count(essay.body)
    lines = brief(essay) + [
        f"Word count: {count}",
        f"Draft: {essay.body[:_BODY_TO_MODEL]}",
        *context,
    ]
    data, model = await _ask(
        ai,
        prompts,
        task=AiTask.ADMIT_ESSAY_COACH,
        name="feedback",
        schema=prompt.SCHEMAS["feedback"],
        locale=locale,
        lines=lines,
        max_tokens=_TOKENS,
    )
    out = Feedback(
        _line(data.get("summary")),
        _lines(data.get("strengths"), prompt.MAX_POINTS),
        _lines(data.get("suggestions"), prompt.MAX_POINTS),
        count,
        essay.word_limit,
    )
    return out, model


def _base_review(
    data: dict[str, Any], essay: EssayInput, exemplars: Sequence[ExemplarMatch]
) -> BaseReview:
    """Turn the model's reply into a base review the code can stand behind."""
    haystack = _flat(essay.body)
    given: dict[str, Any] = {}
    for raw in data.get("dimensions") or []:
        dim = _get(raw, "dim")
        if dim in review.DIMENSIONS and dim not in given:
            given[dim] = raw
    dims = tuple(
        (
            DimensionScore(name, 0, None, "")
            if (raw := given.get(name)) is None
            else DimensionScore(
                name,
                min(max(_int(_get(raw, "score")), 0), CHECK_MAX_SCORE),
                _verbatim(_get(raw, "quote"), haystack),
                _line(_get(raw, "comment")),
            )
        )
        for name in review.DIMENSIONS
    )
    score = round(sum(d.score for d in dims) * 100 / (CHECK_MAX_SCORE * len(dims)))
    count = word_count(essay.body)
    total = len(_paragraphs(essay.body))
    notes: list[ParagraphNote] = []
    for raw in data.get("paragraphs") or []:
        number, note = _int(_get(raw, "paragraph")), _line(_get(raw, "note"))
        if 1 <= number <= total and note:
            notes.append(ParagraphNote(number, note))
    by_id = {str(m.exemplar.id): m.exemplar for m in exemplars}
    patterns: list[ExemplarPattern] = []
    for raw in data.get("patterns") or []:
        ex = by_id.get(str(_get(raw, "exemplar_id") or "").strip())
        text = _line(_get(raw, "pattern"))
        if ex is not None and text and len(patterns) < MAX_LIST:
            patterns.append(
                ExemplarPattern(ex.id, ex.title, ex.school_name, ex.source_url, text)
            )
    limit = essay.word_limit
    return BaseReview(
        score=score,
        band=band_of(score),
        dimensions=dims,
        summary=_summary(data.get("summary")),
        strengths=tuple(_lines(data.get("strengths"), MAX_LIST)),
        improvements=tuple(_lines(data.get("improvements"), MAX_LIST)),
        paragraphs=tuple(notes[: review.MAX_PARAGRAPHS]),
        patterns=tuple(patterns),
        word_count=count,
        word_limit=limit,
        over_limit=limit is not None and count > limit,
        generic=sum(1 for d in dims if d.score <= 1) >= CHECK_GENERIC_DIMS,
    )


def is_degenerate(review: BaseReview) -> bool:
    """A base review that is a scoring failure: every dimension at 0 or no feedback.

    The schema accepts it, but real essays are uneven: an all-zero score or an empty
    summary means the model did not do the work, so the reply is not stored.
    """
    return all(d.score == 0 for d in review.dimensions) or not review.summary.strip()


_BASE_ATTEMPTS: Final = 2


class DegenerateReviewError(AiProviderError):
    """The model twice returned an all-zero or empty review: the provider path."""


async def run_base_review(
    ai: StructuredAi,
    prompts: PromptSource,
    *,
    essay: EssayInput,
    exemplars: Sequence[ExemplarMatch],
    locale: str,
) -> tuple[BaseReview, str]:
    """Review the essay on its own against the rubric and the exemplars."""
    lines = brief(essay) + [
        f"Word count: {word_count(essay.body)}",
        f"Essay: {essay.body[:_BODY_TO_MODEL]}",
    ]
    for m in exemplars:
        ex = m.exemplar
        lines.append(
            f"[exemplar id={ex.id}] {ex.school_name} {ex.kind}: "
            f"{ex.body[:_EXEMPLAR_TO_MODEL]}"
        )
    for _ in range(_BASE_ATTEMPTS):
        data, model = await _ask(
            ai,
            prompts,
            task=AiTask.ADMIT_ESSAY_REVIEW,
            name="base",
            schema=review.SCHEMAS["base"],
            locale=locale,
            lines=lines,
            max_tokens=_REVIEW_TOKENS,
        )
        result = _base_review(data, essay, exemplars)
        if not is_degenerate(result):
            return result, model
    raise DegenerateReviewError()


def _uni_review(data: dict[str, Any], essay: EssayInput, uni: UniContext) -> UniReview:
    """Turn the model's reply into a university review over the listed goals."""
    haystack = _flat(essay.body)
    given: dict[str, Any] = {}
    for raw in data.get("goals") or []:
        key = str(_get(raw, "key") or "")
        given.setdefault(key, raw)
    goals: list[GoalAlignment] = []
    for g in uni.goals:
        raw = given.get(g.key)
        level = _get(raw, "alignment") if raw is not None else "missing"
        goals.append(
            GoalAlignment(
                key=g.key,
                goal=g.text,
                source_url=g.source_url,
                alignment=level if level in ALIGNMENTS else "missing",
                evidence=(
                    None if raw is None else _verbatim(_get(raw, "evidence"), haystack)
                ),
                suggestion="" if raw is None else _line(_get(raw, "suggestion")),
            )
        )
    return UniReview(
        institution_id=uni.institution_id,
        institution_name=uni.name,
        alignment=min(max(_int(data.get("alignment")), 0), 100),
        goals=tuple(goals),
        fit_summary=_summary(data.get("fit_summary")),
        supplement_tips=tuple(_lines(data.get("supplement_tips"), MAX_LIST)),
        risks=tuple(_lines(data.get("risks"), MAX_LIST)),
        sourced=True,
        ao_reaction=_ao_reaction(data.get("ao_reaction")),
    )


def _ao_reaction(raw: Any) -> AoReaction | None:
    if not isinstance(raw, dict):
        return None
    out = AoReaction(
        _summary(raw.get("summary")),
        tuple(_lines(raw.get("likely_positive"), MAX_LIST)),
        tuple(_lines(raw.get("likely_concerns"), MAX_LIST)),
    )
    return out if out.summary or out.likely_positive or out.likely_concerns else None


def unsourced_review(uni: UniContext) -> UniReview:
    """The empty review of a university without sourced goals (no model call)."""
    return UniReview(
        institution_id=uni.institution_id,
        institution_name=uni.name,
        alignment=0,
        goals=(),
        fit_summary="",
        supplement_tips=(),
        risks=(),
        sourced=False,
    )


def uni_lines(uni: UniContext) -> list[str]:
    """The university facts as the model reads them (also the cache input)."""
    lines = [f"University: {uni.name} ({uni.country})"]
    lines += [f"[goal key={g.key}] {g.text}" for g in uni.goals]
    lines += [f"[supplement] {s}" for s in uni.supplements]
    return lines


async def run_uni_review(
    ai: StructuredAi,
    prompts: PromptSource,
    *,
    essay: EssayInput,
    uni: UniContext,
    base: BaseReview | None,
    locale: str,
    exemplars: Sequence[ExemplarMatch] = (),
) -> tuple[UniReview, str]:
    """Judge the fit with one university; no call when nothing is sourced."""
    if not uni.sourced:
        return unsourced_review(uni), ""
    lines = brief(essay) + [
        f"Word count: {word_count(essay.body)}",
        f"Essay: {essay.body[:_BODY_TO_MODEL]}",
        *uni_lines(uni),
    ]
    for m in exemplars:
        ex = m.exemplar
        same = ex.institution_id == uni.institution_id
        lines.append(
            f"[exemplar {'this-university' if same else 'similar-tier'}] "
            f"{ex.school_name} {ex.kind}: {ex.body[:_EXEMPLAR_TO_MODEL]}"
        )
    if base is not None:
        lines.append(f"Base review: {base.score}/100 ({base.band}). {base.summary}")
    data, model = await _ask(
        ai,
        prompts,
        task=AiTask.ADMIT_ESSAY_UNI_REVIEW,
        name="uni",
        schema=review.SCHEMAS["uni"],
        locale=locale,
        lines=lines,
        max_tokens=_REVIEW_TOKENS,
    )
    return _uni_review(data, essay, uni), model


def _fact_texts(value: Any) -> list[str]:
    items = value if isinstance(value, list | tuple) else [value]
    return [t for t in (_line(v) for v in items) if t]


async def load_uni_context(
    uow: AdmissionUnitOfWork, institution_id: UUID
) -> UniContext | None:
    """The sourced goals and current supplemental prompts of a university.

    Only facts and prompts with a source URL count; None when the institution
    is unknown or archived.
    """
    inst = await uow.catalog.institution(institution_id)
    if inst is None:
        return None
    goals: list[UniGoal] = []
    for key in GOAL_FACTS:
        fact = inst.fact(key)
        if fact is None or not fact.source_url:
            continue
        texts = _fact_texts(fact.value)
        for i, text in enumerate(texts):
            goal_key = key if len(texts) == 1 else f"{key}_{i + 1}"
            goals.append(UniGoal(goal_key, text, fact.source_url))
    cycles = await uow.supp_prompts.by_cycle(institution_id)
    latest = cycles[max(cycles)] if cycles else []
    supplements = tuple(
        _line(p.prompt)
        for p in sorted(latest, key=lambda p: p.position)
        if p.source_url and p.prompt.strip()
    )
    return UniContext(
        institution_id=inst.id,
        name=inst.name,
        country=inst.country,
        goals=tuple(goals),
        supplements=supplements,
    )


def check_payload(check: EssayCheck) -> dict[str, Any]:
    """The stored JSON of a check."""
    return asdict(check)


def check_from(payload: Mapping[str, Any]) -> EssayCheck:
    """A check from its stored JSON."""
    dims = [CheckDimension(**d) for d in payload["dimensions"]]
    return EssayCheck(**{**payload, "dimensions": dims})


def base_payload(base: BaseReview) -> dict[str, Any]:
    """The stored JSON of a base review (UUIDs as strings)."""
    out = asdict(base)
    for p in out["patterns"]:
        p["exemplar_id"] = str(p["exemplar_id"])
    return out


def base_from(payload: Mapping[str, Any]) -> BaseReview:
    """A base review from its stored JSON."""
    return BaseReview(
        **{
            **payload,
            "dimensions": tuple(DimensionScore(**d) for d in payload["dimensions"]),
            "strengths": tuple(payload["strengths"]),
            "improvements": tuple(payload["improvements"]),
            "paragraphs": tuple(ParagraphNote(**p) for p in payload["paragraphs"]),
            "patterns": tuple(
                ExemplarPattern(**{**p, "exemplar_id": UUID(p["exemplar_id"])})
                for p in payload["patterns"]
            ),
        }
    )


def uni_payload(uni: UniReview) -> dict[str, Any]:
    """The stored JSON of a university review (UUIDs as strings)."""
    out = asdict(uni)
    out["institution_id"] = str(uni.institution_id)
    return out


def uni_from(payload: Mapping[str, Any]) -> UniReview:
    """A university review from its stored JSON."""
    return UniReview(
        **{
            **payload,
            "institution_id": UUID(payload["institution_id"]),
            "goals": tuple(GoalAlignment(**g) for g in payload["goals"]),
            "supplement_tips": tuple(payload["supplement_tips"]),
            "risks": tuple(payload["risks"]),
            "ao_reaction": (
                None
                if not payload.get("ao_reaction")
                else AoReaction(
                    payload["ao_reaction"]["summary"],
                    tuple(payload["ao_reaction"]["likely_positive"]),
                    tuple(payload["ao_reaction"]["likely_concerns"]),
                )
            ),
        }
    )


def input_key(*parts: str) -> str:
    """A stable text over the inputs of a model call (digested before storage)."""
    return "\x1f".join(hashlib.sha256(p.encode()).hexdigest() for p in parts)


def check_key(essay: EssayInput, locale: str) -> str:
    """The input key of a coach check: the text it reads and the prompt version."""
    return input_key(
        "check",
        locale,
        essay.kind,
        essay.title,
        essay.prompt_text,
        str(essay.word_limit),
        essay.body,
        prompt.CHECK,
    )
