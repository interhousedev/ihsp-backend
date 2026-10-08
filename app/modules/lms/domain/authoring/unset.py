"""A sentinel for optional arguments where None is a meaningful value."""

from typing import Final


class Unset:
    """Marks an argument that was not provided."""

    __slots__ = ()

    def __repr__(self) -> str:
        """Return a readable name."""
        return "UNSET"


UNSET: Final = Unset()
