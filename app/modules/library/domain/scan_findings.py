"""What the scan job looks for in a material (doc § 3.5).

Findings are shown to librarians and change no status. Only codes are kept, never the
matched text, so the scan result holds no copy of the personal data it found.
"""

import re
from enum import StrEnum


class FindingCode(StrEnum):
    """Stable codes of scan findings; the queue shows `library-finding-<code>`."""

    PHONE_NUMBER = "phone_number"
    EMAIL = "email"
    HANDLE = "handle"
    EXAM_MARKER = "exam_marker"
    DUPLICATE = "duplicate"


# +998 90 123 45 67, 998901234567: the country code is enough to call it a phone.
_PHONE_WITH_CODE = re.compile(
    r"(?<!\d)\+?998[\s\-()]*\d{2}[\s\-()]*\d{3}[\s\-]*\d{2}[\s\-]*\d{2}(?!\d)"
)
# 90 123 45 67, (90) 123-45-67: without the code the groups must be separated, so a
# plain nine-digit number in a physics text is not flagged.
_PHONE_GROUPED = re.compile(
    r"(?<![\d.])\(?\d{2}\)?[\s\-]\d{3}[\s\-]\d{2}[\s\-]\d{2}(?!\d)"
)
_EMAIL = re.compile(r"[\w.+\-]+@[\w\-]+(?:\.[\w\-]+)+")
_HANDLE = re.compile(r"(?<![\w@.])@[A-Za-z][\w]{3,31}\b")

_EXAM_MARKERS = re.compile(
    "|".join(
        [
            r"oraliq\s+nazorat",
            r"yakuniy\s+nazorat",
            r"оралиқ\s+назорат",
            r"якуний\s+назорат",
            r"рубежн\w*\s+контрол\w*",
            r"\bmidterm\b",
            r"\bfinal\b",
            r"\bvariant\s*(?:№|#|no\.?|n)?\s*\d+",
            r"\bвариант\s*(?:№|#)?\s*\d+",
        ]
    ),
    re.IGNORECASE,
)


def personal_data_findings(text: str) -> list[FindingCode]:
    """Phone numbers, e-mail addresses and @handles found in the text."""
    found: list[FindingCode] = []
    if _PHONE_WITH_CODE.search(text) or _PHONE_GROUPED.search(text):
        found.append(FindingCode.PHONE_NUMBER)
    if _EMAIL.search(text):
        found.append(FindingCode.EMAIL)
    if _HANDLE.search(text):
        found.append(FindingCode.HANDLE)
    return found


def exam_marker_findings(text: str) -> list[FindingCode]:
    """`exam_marker` when the text looks like a paper of a control."""
    return [FindingCode.EXAM_MARKER] if _EXAM_MARKERS.search(text) else []


def scan_material_text(text: str) -> list[FindingCode]:
    """All text findings of a material, each code once."""
    return [*personal_data_findings(text), *exam_marker_findings(text)]
