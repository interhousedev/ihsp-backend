"""Speech to text for the chat input: the caps and the audio formats it accepts.

The recording is sent to the model once and never stored. The byte cap is the hard
bound on what is read; the duration is what the client reports for the recording.
"""

from typing import Final

# The byte cap is the bound on cost: the duration is client-reported. 1 MB holds
# about 120 s of low-bitrate speech (the bot's Telegram voice notes fit too).
MAX_BYTES: Final = 1024 * 1024
MAX_SECONDS: Final = 120
# Requests a minute per student; the limit is shared by all processes (Redis).
RATE_PER_MINUTE: Final = 10
RATE_WINDOW_SECONDS: Final = 60
# A transcript is a few sentences; the answer budget is small.
MAX_OUTPUT_TOKENS: Final = 1000
# MIME type -> the `format` of an OpenRouter `input_audio` part.
AUDIO_FORMATS: Final[dict[str, str]] = {
    "audio/wav": "wav",
    "audio/x-wav": "wav",
    "audio/wave": "wav",
    "audio/mpeg": "mp3",
    "audio/mp3": "mp3",
    "audio/ogg": "ogg",
    "audio/webm": "webm",  # MediaRecorder (Opus in WebM) in the web chat
    "audio/flac": "flac",
    "audio/x-flac": "flac",
    "audio/mp4": "m4a",
    "audio/m4a": "m4a",
    "audio/aac": "aac",
}


# The bytes decide the format: libmagic names the container, the client's claim is
# not trusted. video/webm is kept because libmagic reports audio-only WebM that way
# (the web chat records WebM); video/mp4 is left out so a video is not read as audio.
SNIFF_BYTES: Final = 4096
SNIFFED_FORMATS: Final[dict[str, str]] = {
    "audio/wav": "wav",
    "audio/x-wav": "wav",
    "audio/wave": "wav",
    "audio/mpeg": "mp3",
    "audio/mp3": "mp3",
    "audio/ogg": "ogg",
    "application/ogg": "ogg",
    "audio/webm": "webm",
    "video/webm": "webm",
    "audio/flac": "flac",
    "audio/x-flac": "flac",
    "audio/mp4": "m4a",
    "audio/x-m4a": "m4a",
    "audio/aac": "aac",
    "audio/x-hx-aac-adts": "aac",
}


def sniffed_format(mime: str | None) -> str | None:
    """The OpenRouter audio format of a sniffed MIME type, or None (not audio)."""
    return SNIFFED_FORMATS.get((mime or "").strip().lower())


def audio_format(content_type: str | None) -> str | None:
    """The OpenRouter audio format of a MIME type (parameters ignored), or None."""
    base = (content_type or "").split(";", 1)[0].strip().lower()
    return AUDIO_FORMATS.get(base)
