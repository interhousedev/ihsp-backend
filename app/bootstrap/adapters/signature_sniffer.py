"""Development fallback for ContentSniffer when libmagic is not installed.

Production always has libmagic (the image installs libmagic1); a developer machine
without `brew install libmagic` can still run the stack with this look-up of the
well-known signatures.
"""

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
JPEG_SIGNATURE = b"\xff\xd8\xff"
ZIP_SIGNATURE = b"PK\x03\x04"
PDF_SIGNATURE = b"%PDF-"


class SignatureSniffer:
    """ContentSniffer that knows PDF, PNG, JPEG, ZIP (Office) and plain text."""

    async def sniff(self, head: bytes) -> str:
        """Return the MIME type of the first bytes of a file."""
        if head.startswith(PDF_SIGNATURE):
            return "application/pdf"
        if head.startswith(PNG_SIGNATURE):
            return "image/png"
        if head.startswith(JPEG_SIGNATURE):
            return "image/jpeg"
        if head.startswith(ZIP_SIGNATURE):
            return "application/zip"
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
