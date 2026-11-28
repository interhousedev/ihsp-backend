"""Voiceover model (spec 3.3): script invariants, captions, TTS port fake.

The implementation must provide:
- `app.shared.contracts.speech`: `SpeechSynthesizer` protocol with
  `async synthesize(*, text, language, voice_id, speed=1.0) -> SynthesisResult`;
  `SynthesisResult(audio: bytes, duration_ms: int, word_timings: tuple[WordTiming-like
  (word,start_ms,end_ms)], chars_billed: int)`.
- `app.modules.media.domain.narration`: `Segment(id, speaker, text, start_ms=0,
  end_ms=0, source_refs=())` frozen; `NarrationOptions(style, length, language,
  voice_id, speed)`; `validate_script(segments, *, language, max_chars)` raising
  `NarrationInvalidError` (ValidationFailedError) when empty, over `max_chars`,
  a blank segment, or the script language differs from the requested one
  (detected by `detect_language(text) -> "uz"|"ru"|"en"`); `build_vtt(segments) ->
  str` WebVTT; `align_segments(segments, durations_ms)` -> segments with contiguous
  start/end.
- `timecode(ms) -> "mm:ss"` (minutes may exceed 59).
Synthesis is no longer a job of its own: voice and render are two stages of ONE
`MediaJob` (see `test_media_job.py`).
Chosen boring: captions use provider word timings only for segment boundaries; cue
per segment.
"""

from typing import Any

from app.modules.media.domain.narration import (
    NarrationInvalidError,
    Segment,
    align_segments,
    build_vtt,
    timecode,
    validate_script,
)
from app.shared.base_error import ValidationFailedError

import pytest


def seg(i: int, text: str, speaker: str = "teacher") -> Segment:
    return Segment(id=f"s{i}", speaker=speaker, text=text)


def test_valid_script_passes() -> None:
    validate_script(
        [seg(1, "Hello class"), seg(2, "Today we study light")],
        language="en",
        max_chars=1000,
    )


@pytest.mark.parametrize(
    "segments,language,limit",
    [
        ([], "en", 100),
        ([seg(1, "   ")], "en", 100),
        ([seg(1, "x" * 50)], "en", 49),
        ([seg(1, "Привет, сегодня мы изучаем свет и оптику")], "en", 1000),
    ],
)
def test_invalid_scripts_are_refused(segments: Any, language: Any, limit: int) -> None:
    with pytest.raises(NarrationInvalidError) as err:
        validate_script(segments, language=language, max_chars=limit)
    assert isinstance(err.value, ValidationFailedError)


def test_align_makes_contiguous_cues() -> None:
    aligned = align_segments([seg(1, "a"), seg(2, "b"), seg(3, "c")], [1000, 500, 250])

    assert [(s.start_ms, s.end_ms) for s in aligned] == [
        (0, 1000),
        (1000, 1500),
        (1500, 1750),
    ]


def test_vtt_has_header_and_timestamps() -> None:
    segments = align_segments([seg(1, "Hello"), seg(2, "World")], [1500, 2250])

    vtt = build_vtt(segments)

    assert vtt.startswith("WEBVTT")
    assert "00:00:00.000 --> 00:00:01.500\nHello" in vtt
    assert "00:00:01.500 --> 00:00:03.750\nWorld" in vtt


def test_timecode_is_minutes_and_seconds() -> None:
    """`timecode(ms)` is the "mm:ss" a notebook citation points to ("02:14")."""
    assert timecode(0) == "00:00"
    assert timecode(134_000) == "02:14"
    assert timecode(3_725_000) == "62:05"
