"""A marker for "this field was not sent" in PATCH requests (`None` clears a field)."""

from enum import Enum


class Unset(Enum):
    """The only value of the "not sent" marker."""

    UNSET = "unset"


UNSET = Unset.UNSET
