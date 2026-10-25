"""Sentinel for "field not sent" in partial updates (None means "clear it")."""


class Unset:
    """Type of the UNSET sentinel."""

    __slots__ = ()

    def __repr__(self) -> str:
        """Return a readable name."""
        return "UNSET"

    def __bool__(self) -> bool:
        """The sentinel is falsy."""
        return False


UNSET = Unset()
