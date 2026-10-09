"""Dotted version numbers of the installed app: parse and compare them."""

import re

_VERSION = re.compile(r"[0-9]{1,9}(\.[0-9]{1,9})*")


def parse_version(text: str) -> tuple[int, ...]:
    """Split "1.4.2" into (1, 4, 2); anything but dotted integers raises ValueError."""
    if _VERSION.fullmatch(text) is None:
        raise ValueError(
            f"invalid version {text!r}: use dotted non-negative integers like 1.4.2"
        )
    return tuple(int(part) for part in text.split("."))


def compare_versions(left: str, right: str) -> int:
    """Return -1, 0 or 1 as left is older than, equal to or newer than right.

    Segments compare as numbers ("1.10.0" is newer than "1.9.0") and a missing
    segment counts as 0 ("1.4" equals "1.4.0").
    """
    a = parse_version(left)
    b = parse_version(right)
    width = max(len(a), len(b))
    padded_a = a + (0,) * (width - len(a))
    padded_b = b + (0,) * (width - len(b))
    return (padded_a > padded_b) - (padded_a < padded_b)
