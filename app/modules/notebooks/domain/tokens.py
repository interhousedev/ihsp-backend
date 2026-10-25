"""Token estimates and the weighted-token budget formula (§ 3.3.2, § 3.6)."""

import math
from dataclasses import dataclass
from typing import Any, Final

CHARS_PER_TOKEN: Final = 2.8  # conservative for Cyrillic and Uzbek
CACHED_WEIGHT: Final = 0.1
OUTPUT_WEIGHT: Final = 5


def estimate_tokens(chars: int) -> int:
    """Return ``ceil(chars / 2.8)``, computed in integers (``ceil(chars * 5 / 14)``).

    The float division rounds up at exact multiples (``2800 / 2.8`` is
    ``1000.0000000000001``), which would count one token too many.
    """
    return -(-chars * 5 // 14) if chars > 0 else 0


def estimate_cost(chars: int, max_tokens: int) -> int:
    """Weighted estimate before a call: ``ceil(chars / 2.8) + max_tokens * 5``."""
    return estimate_tokens(chars) + max_tokens * OUTPUT_WEIGHT


@dataclass(frozen=True, slots=True)
class Usage:
    """Provider usage of one call; `cached` is a subset of `input`."""

    input: int = 0
    output: int = 0
    cached: int = 0
    cost_micro: int | None = None

    @property
    def weighted(self) -> int:
        """``input_uncached + 0.1 x cached + 5 x output`` (rounded up)."""
        uncached = max(self.input - self.cached, 0)
        return math.ceil(
            uncached + CACHED_WEIGHT * self.cached + OUTPUT_WEIGHT * self.output
        )

    def __add__(self, other: "Usage") -> "Usage":
        """Sum two usages (a repair call adds to the first call)."""
        cost = (
            None
            if self.cost_micro is None and other.cost_micro is None
            else (self.cost_micro or 0) + (other.cost_micro or 0)
        )
        return Usage(
            self.input + other.input,
            self.output + other.output,
            self.cached + other.cached,
            cost,
        )

    @classmethod
    def from_gateway(cls, raw: dict[str, Any]) -> "Usage":
        """Build from the gateway's ``usage`` dict."""
        cost = raw.get("cost_micro")
        return cls(
            input=int(raw.get("input", 0)),
            output=int(raw.get("output", 0)),
            cached=int(raw.get("cached", 0)),
            cost_micro=int(cost) if cost is not None else None,
        )
