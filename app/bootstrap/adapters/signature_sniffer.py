"""Development fallback for ContentSniffer when libmagic is not installed.

Production always has libmagic (the image installs libmagic1); a developer machine
without `brew install libmagic` can still run the stack with this look-up of the
well-known signatures.
"""

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
JPEG_SIGNATURE = b"\xff\xd8\xff"
ZIP_SIGNATURE = b"PK\x03\x04"
PDF_SIGNATURE = b"%PDF-"
OGG_SIGNATURE = b"OggS"
FLAC_SIGNATURE = b"fLaC"
MP3_TAG = b"ID3"
WEBM_SIGNATURE = b"\x1a\x45\xdf\xa3"


_SIGNATURES: tuple[tuple[bytes, str], ...] = (
    (PDF_SIGNATURE, "application/pdf"),
    (PNG_SIGNATURE, "image/png"),
    (JPEG_SIGNATURE, "image/jpeg"),
    (ZIP_SIGNATURE, "application/zip"),
    (OGG_SIGNATURE, "audio/ogg"),
    (FLAC_SIGNATURE, "audio/flac"),
    (MP3_TAG, "audio/mpeg"),
    (WEBM_SIGNATURE, "video/webm"),
)


class SignatureSniffer:
    """ContentSniffer that knows PDF, PNG, JPEG, ZIP (Office), audio and plain text."""

    async def sniff(self, head: bytes) -> str:
        """Return the MIME type of the first bytes of a file."""
        for signature, mime in _SIGNATURES:
            if head.startswith(signature):
                return mime
        if head[:4] == b"RIFF" and head[8:12] == b"WAVE":
            return "audio/wav"
        if _is_text(head):
            return "text/plain"
        return "application/octet-stream"


def _is_text(head: bytes) -> bool:
    if b"\x00" in head:
        return False
    try:
        head.decode("utf-8")
    except UnicodeDecodeError as exc:
        # The head may end in the middle of a character.
        return exc.start >= len(head) - 3
    return True
