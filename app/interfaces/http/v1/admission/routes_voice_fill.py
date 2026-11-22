"""Voice fill: `POST /v1/admission/voice-fill` (spoken text into form fields)."""

import re
from typing import Literal

from app.interfaces.http.v1.admission.deps import AdmissionCtx, ContainerDep
from app.interfaces.http.v1.admission.routes_items import LocaleHeader, _locale
from app.modules.admission.application.voice_fill import (
    TEXT_MAX,
    TRANSCRIPT_MAX,
    VoiceField,
)
from app.modules.admission.infrastructure.ai.prompts.voice_fill import MAX_FIELDS

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

router = APIRouter(prefix="/v1/admission", tags=["admission"])

KEY_PATTERN = r"^[a-z][a-z0-9_]{0,39}$"
_OPTION_BAD = re.compile(r"[|\n]")


class VoiceFieldIn(BaseModel):
    """One field of the caller's form."""

    model_config = ConfigDict(extra="forbid")

    key: str = Field(pattern=KEY_PATTERN)
    label: str = Field(min_length=1, max_length=200)
    kind: Literal["text", "number", "choice"] = "text"
    options: list[str] = Field(default_factory=list, max_length=12)
    max_length: int = Field(default=TEXT_MAX, ge=1, le=TEXT_MAX)


class VoiceFillIn(BaseModel):
    """What the person said and the fields to fill from it."""

    model_config = ConfigDict(extra="forbid")

    form: str = Field(min_length=1, max_length=60)
    transcript: str = Field(min_length=1, max_length=TRANSCRIPT_MAX)
    fields: list[VoiceFieldIn] = Field(min_length=1, max_length=MAX_FIELDS)


class VoiceFillOut(BaseModel):
    """The values found; a field the person did not speak about is absent."""

    values: dict[str, str]


async def voice_fill(
    body: VoiceFillIn,
    container: ContainerDep,
    ctx: AdmissionCtx,
    accept_language: LocaleHeader = None,
) -> VoiceFillOut:
    """Extract the field values from a transcript (soft limit: 60 per hour)."""
    fields = [
        VoiceField(
            key=f.key,
            label=f.label,
            kind=f.kind,
            options=tuple(_OPTION_BAD.sub(" ", o).strip()[:60] for o in f.options),
            max_length=f.max_length,
        )
        for f in body.fields
    ]
    values = await container.admission.voice_fill.fill(
        ctx, fields, body.transcript, _locale(accept_language)
    )
    return VoiceFillOut(values=values)


router.add_api_route(
    "/voice-fill",
    voice_fill,
    methods=["POST"],
    response_model=VoiceFillOut,
    operation_id="admission_voice_fill",
)
