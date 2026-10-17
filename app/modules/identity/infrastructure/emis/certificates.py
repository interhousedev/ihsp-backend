"""Certificates of the EMIS profile (``dtm_certificate_info``) as contract objects."""

import datetime as dt
from typing import Any

from app.shared.contracts.emis import EmisCertificate

INFO_KEY = "dtm_certificate_info"


def _text(value: Any) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(str(value).strip().replace(",", "."))
    except ValueError:
        return None


def _day(value: Any) -> dt.date | None:
    raw = _text(value)
    if raw is None:
        return None
    try:
        return dt.date.fromisoformat(raw[:10])
    except ValueError:
        return None


def _items(info: dict[str, Any], key: str) -> list[dict[str, Any]]:
    raw = info.get(key)
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, dict)]


def _cefr(item: dict[str, Any]) -> EmisCertificate:
    return EmisCertificate(
        kind="cefr",
        level=_text(item.get("level")),
        score=_number(item.get("ball")),
        percent=None,
        subject=_text(item.get("subject")),
        issued_on=_day(item.get("start_date")),
        expires_on=_day(item.get("end_date")),
        serial=_text(item.get("ser_num")),
        url=_text(item.get("hash")),
    )


def _national(item: dict[str, Any]) -> EmisCertificate:
    return EmisCertificate(
        kind="national",
        level=_text(item.get("level")),
        score=_number(item.get("ball")),
        percent=_number(item.get("percent")),
        subject=_text(item.get("science_name")),
        issued_on=_day(item.get("start_at")),
        expires_on=_day(item.get("end_at")),
        serial=_text(item.get("cert_number")),
        url=_text(item.get("url")),
    )


def to_certificates(result: dict[str, Any]) -> list[EmisCertificate]:
    """Map the profile ``result`` object; a missing or odd block gives nothing."""
    info = result.get(INFO_KEY)
    if not isinstance(info, dict):
        return []
    found = [_cefr(item) for item in _items(info, "cefr")]
    found.extend(_national(item) for item in _items(info, "national"))
    return found
