"""Voice answers: which recordings are read and how read-aloud audio is packed.

A recording lives only in memory for the one transcription call and is never
stored; only the text is kept. The format comes from the bytes, never from the
client's content type.
"""

import struct
from typing import Final

SNIFF_BYTES: Final = 16
FORMATS: Final = ("webm", "ogg", "wav", "mp3", "m4a")
RATE_PER_MINUTE: Final = 10
RATE_WINDOW_SECONDS: Final = 60
PCM_RATE: Final = 24_000
"""Sample rate of the PCM the speech model returns (16-bit mono)."""


def sniff(head: bytes) -> str | None:
    """The audio container of a recording from its first bytes, or None."""
    if head.startswith(b"\x1a\x45\xdf\xa3"):
        return "webm"  # MediaRecorder in Chrome and Firefox (Opus in WebM)
    if head.startswith(b"OggS"):
        return "ogg"
    if head[:4] == b"RIFF" and head[8:12] == b"WAVE":
        return "wav"
    if head[4:8] == b"ftyp":
        return "m4a"  # MediaRecorder in Safari (AAC in MP4)
    if head.startswith(b"ID3") or head[:2] in (b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"):
        return "mp3"
    return None


def wav(pcm: bytes, *, rate: int = PCM_RATE) -> bytes:
    """Wrap 16-bit mono PCM in a WAV header so a browser can play it."""
    size = len(pcm)
    header = b"RIFF" + struct.pack("<I", 36 + size) + b"WAVE"
    header += b"fmt " + struct.pack("<IHHIIHH", 16, 1, 1, rate, rate * 2, 2, 16)
    header += b"data" + struct.pack("<I", size)
    return header + pcm


def silence(seconds: float = 0.2) -> bytes:
    """A short silent WAV (what fake mode reads aloud)."""
    return wav(b"\x00\x00" * int(PCM_RATE * seconds))
