"""Locale negotiation for the public HTML pages."""

SUPPORTED = ("uz", "ru", "en")
DEFAULT_LOCALE = "ru"


def _parse_item(item: str) -> tuple[float, str]:
    tag, _, params = item.strip().partition(";")
    quality = 1.0
    for param in params.split(";"):
        name, _, value = param.strip().partition("=")
        if name.strip() == "q":
            try:
                quality = float(value)
            except ValueError:
                quality = 0.0
    return quality, tag.strip().lower().split("-")[0]


def pick_locale(accept_language: str | None) -> str:
    """Pick uz, ru or en from an Accept-Language header; default ru."""
    if not accept_language:
        return DEFAULT_LOCALE
    items = [_parse_item(part) for part in accept_language.split(",") if part.strip()]
    for quality, tag in sorted(items, key=lambda pair: -pair[0]):
        if quality > 0 and tag in SUPPORTED:
            return tag
    return DEFAULT_LOCALE
