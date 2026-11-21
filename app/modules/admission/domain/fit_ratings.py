"""Validation of the fit preference ratings (the mapping to weights is in `fit.py`)."""

from app.modules.admission.domain.errors import InvalidAnswerError
from app.modules.admission.domain.fit import (
    RATING_KEYS,
    RATING_MAX,
    RATING_MIN,
    default_ratings,
)


def clean_ratings(raw: dict[str, int]) -> dict[str, int]:
    """All eight ratings, each 1..10; unknown keys and out-of-range values refused."""
    unknown = set(raw) - set(RATING_KEYS)
    if unknown:
        raise InvalidAnswerError(params={"question": sorted(unknown)[0]})
    out = default_ratings() | raw
    for key, value in out.items():
        if isinstance(value, bool) or not RATING_MIN <= value <= RATING_MAX:
            raise InvalidAnswerError(params={"question": key})
    return out
