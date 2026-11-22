"""Voice fill: a spoken answer (as text) becomes the values of a form's fields."""

import re
from dataclasses import dataclass
from typing import Any, Final, Literal

from app.modules.admission.application.actor import AdmissionContext
from app.modules.admission.application.review_checks import nfc
from app.modules.admission.application.words import delimit, plain
from app.modules.admission.domain.errors import ConsentRequiredError
from app.modules.admission.infrastructure.ai.prompts import voice_fill as prompt
from app.modules.admission.ports.ai import PromptSource, StructuredAi
from app.modules.admission.ports.consent import AI, PurposeConsents
from app.shared.ai_tasks import AiTask
from app.shared.base_error import ValidationFailedError
from app.shared.brand import with_brand
from app.shared.rate_limit import RateLimiter

FieldKind = Literal["text", "number", "choice"]

TRANSCRIPT_MAX: Final = 6000
TEXT_MAX: Final = 1500
_HOUR: Final = 3600
_PER_HOUR: Final = 60
_TOKENS: Final = 2500
_NUMBER = re.compile(r"-?\d+(?:[.,]\d+)?")
_LABEL_BAD = re.compile(r"[()\[\]\n]+")


@dataclass(frozen=True, slots=True)
class VoiceField:
    """One field of the form the caller wants filled."""

    key: str
    label: str
    kind: FieldKind
    options: tuple[str, ...] = ()
    max_length: int = TEXT_MAX


def _line(field: VoiceField) -> str:
    label = " ".join(_LABEL_BAD.sub(" ", field.label).split())
    options = f"; options: {' | '.join(field.options)}" if field.options else ""
    return f"[field {field.key}] {label} (kind: {field.kind}{options})"


def voice_lines(fields: list[VoiceField], transcript: str, locale: str) -> list[str]:
    """The model input: the field list and the flattened transcript."""
    return [
        f"Language: {locale}",
        *(_line(f) for f in fields),
        f"[transcript] {' '.join(transcript.split())}",
    ]


def _number(raw: str) -> str:
    found = _NUMBER.search(raw)
    if found is None:
        return ""
    value = float(found.group().replace(",", "."))
    return str(int(value)) if value == int(value) else str(round(value, 2))


def clean_values(data: Any, fields: list[VoiceField]) -> dict[str, str]:
    """Keep one valid value per known key; empty, unknown or off-list ones go."""
    by_key = {f.key: f for f in fields}
    rows = data.get("values") if isinstance(data, dict) else None
    out: dict[str, str] = {}
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        field = by_key.get(str(row.get("key")))
        raw = row.get("value")
        if field is None or field.key in out or not isinstance(raw, str):
            continue
        text = nfc(plain(raw)).strip()
        if field.kind == "number":
            text = _number(text)
        elif field.kind == "choice":
            wanted = text.casefold()
            text = next((o for o in field.options if o.casefold() == wanted), "")
        else:
            text = text[: field.max_length]
        if text:
            out[field.key] = text
    return out


def check_fields(fields: list[VoiceField]) -> None:
    """Reject duplicate keys and a choice field without options."""
    keys = [f.key for f in fields]
    if len(set(keys)) != len(keys):
        raise ValidationFailedError(params={"field": "fields"})
    if any(f.kind == "choice" and not f.options for f in fields):
        raise ValidationFailedError(params={"field": "options"})


class VoiceFillService:
    """Extract field values from a transcript with the `admit_voice_fill` task."""

    def __init__(
        self,
        ai: StructuredAi,
        consents: PurposeConsents,
        prompts: PromptSource,
        limiter: RateLimiter,
    ) -> None:
        """Keep the collaborators."""
        self._ai = ai
        self._consents = consents
        self._prompts = prompts
        self._limiter = limiter

    async def fill(
        self,
        ctx: AdmissionContext,
        fields: list[VoiceField],
        transcript: str,
        locale: str,
    ) -> dict[str, str]:
        """Return the values the transcript supports, keyed by field key."""
        check_fields(fields)
        text = transcript.strip()
        if not text or len(text) > TRANSCRIPT_MAX:
            raise ValidationFailedError(params={"field": "transcript"})
        granted = (await self._consents.granted([ctx.user_id])).get(
            ctx.user_id, frozenset()
        )
        if AI not in granted:
            raise ConsentRequiredError(params={"purpose": AI})
        await self._limiter.hit(
            f"admission:voice_fill:{ctx.user_id}",
            limit=_PER_HOUR,
            window_seconds=_HOUR,
        )
        data, _ = await self._ai.json(
            task=AiTask.ADMIT_VOICE_FILL,
            system=with_brand(
                await self._prompts.text(AiTask.ADMIT_VOICE_FILL, "system", locale)
            ),
            user=delimit(voice_lines(fields, text, locale)),
            schema_name=prompt.SCHEMA_NAME,
            schema=prompt.SCHEMA,
            max_tokens=_TOKENS,
        )
        return clean_values(data, fields)
