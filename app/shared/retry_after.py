"""The `Retry-After` header of an HTTP answer, as seconds."""


def parse_retry_after(raw: str | None) -> float | None:
    """Seconds from a plain-number `Retry-After`; None when missing, odd or negative."""
    if raw is None:
        return None
    try:
        seconds = float(raw)
    except ValueError:
        return None
    return seconds if seconds >= 0 else None
