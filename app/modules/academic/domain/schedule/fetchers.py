"""Which students of a group are asked when EMIS is read for the whole group."""

from collections.abc import Sequence
from uuid import UUID

FETCHERS_PER_GROUP = 2
ATTEMPTS_PER_FETCHER = 3  # students tried in turn until one EMIS link answers


def pick_fetchers(
    members: Sequence[tuple[UUID, int | None]],
    *,
    attempts: int = ATTEMPTS_PER_FETCHER,
) -> list[list[UUID]]:
    """Two students per group: one of each half when split, else any two.

    ``members`` are (user id, subgroup) of one group. Each returned list is one
    fetcher with its stand-ins (tried in order when an EMIS link fails); the lists
    never share a student, so no more than two EMIS readings succeed per group.
    """
    first = [user_id for user_id, half in members if half == 1]
    second = [user_id for user_id, half in members if half == 2]
    if first and second:
        return [first[:attempts], second[:attempts]]
    everyone = [user_id for user_id, _ in members]
    slots = [everyone[i::FETCHERS_PER_GROUP][:attempts] for i in range(2)]
    return [slot for slot in slots if slot]
