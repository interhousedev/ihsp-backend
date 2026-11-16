"""Status machines: one allowed-transition table per aggregate."""

from collections.abc import Mapping

from app.modules.admission.domain.errors import InvalidTransitionError


def check_transition(
    table: Mapping[str, frozenset[str]], current: str, target: str
) -> None:
    """Raise `admission/invalid_transition` unless `current → target` is allowed."""
    if target not in table.get(current, frozenset()):
        raise InvalidTransitionError(params={"status": current, "target": target})
