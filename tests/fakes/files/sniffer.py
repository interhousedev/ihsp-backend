"""A signature-based ContentSniffer for tests (libmagic is a system library)."""


class SignatureSniffer:
    """Recognises the formats the tests use; mimics libmagic's answers."""

    async def sniff(self, head: bytes) -> str:
        """Return a MIME type from magic bytes, or text/plain for printable text."""
        if head.startswith(b"%PDF-"):
            return "application/pdf"
        if head.startswith(b"\x89PNG\r\n\x1a\n"):
            return "image/png"
        if head.startswith(b"\xff\xd8\xff"):
            return "image/jpeg"
        if head.startswith(b"MZ"):
            return "application/x-dosexec"
        if head.startswith(b"PK\x03\x04"):
            return self._zip_type(head)
        return self._text_or_binary(head)

    @staticmethod
    def _zip_type(head: bytes) -> str:
        prefix = "application/vnd.openxmlformats-officedocument."
        if b"word/" in head:
            return prefix + "wordprocessingml.document"
        if b"ppt/" in head:
            return prefix + "presentationml.presentation"
        if b"xl/" in head:
            return prefix + "spreadsheetml.sheet"
        return "application/zip"

    @staticmethod
    def _text_or_binary(head: bytes) -> str:
        """libmagic calls anything without NUL and few control bytes text/plain."""
        if not head:
            return "application/x-empty"
        controls = sum(1 for b in head if b < 9 or 14 <= b < 32)
        if b"\x00" in head or controls * 10 > len(head):
            return "application/octet-stream"
        return "text/plain"
