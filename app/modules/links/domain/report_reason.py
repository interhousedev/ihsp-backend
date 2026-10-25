"""Why a visitor reports a public page (SL-9)."""

from enum import StrEnum


class ReportReason(StrEnum):
    """Report reasons offered on public pages."""

    PHISHING = "phishing"
    MALWARE = "malware"
    PERSONAL_DATA = "personal_data"
    OFFENSIVE = "offensive"
    OTHER = "other"
