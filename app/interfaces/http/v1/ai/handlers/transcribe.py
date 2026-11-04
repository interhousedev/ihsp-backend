"""POST /v1/ai/transcriptions: speech to text for the chat input (audio not stored)."""

from typing import Annotated

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_actor, get_container
from app.interfaces.http.v1.ai.schemas import TranscriptionResponse
from app.modules.ai.domain.voice import MAX_BYTES
from app.shared.actor import Actor

from fastapi import Depends, File, Form, UploadFile


async def transcribe(
    file: Annotated[UploadFile, File()],
    duration_ms: Annotated[int, Form(ge=1)],
    container: Annotated[Container, Depends(get_container)],
    actor: Annotated[Actor, Depends(get_actor)],
) -> TranscriptionResponse:
    """Transcribe one recording (audio up to 1 MiB and 120 seconds, not stored).

    `duration_ms` is the length the client measured; the byte cap bounds the read.
    """
    # Read one byte past the cap so an oversized upload is refused without
    # being buffered in full. The type is sniffed by the use case, not declared.
    data = await file.read(MAX_BYTES + 1)
    text = await container.ai.transcribe_audio.execute(
        actor,
        data=data,
        duration_ms=duration_ms,
    )
    return TranscriptionResponse(text=text)
