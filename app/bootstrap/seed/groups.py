"""Curators, head students and subgroups, set once students are registered."""

from collections.abc import Collection, Sequence
from uuid import UUID

from app.bootstrap.container import Container
from app.bootstrap.seed.homework import demo_student_ids
from app.bootstrap.seed.schedule import Structure
from app.shared.actor import SYSTEM_ACTOR

CURATORS = {"2TN2": "languages", "1TN1": "it"}


async def finish_groups(
    container: Container, structure: Structure, teachers: dict[str, UUID]
) -> None:
    """Curator for each group, the first student as head, students split in two.

    English and Informatics are divided subjects; the demo students sit in
    subgroup 1, so their timetable also shows subgroup 2's lessons, marked.
    """
    schedule = container.academic.schedule
    demo = set(await demo_student_ids(container))
    for key, group_id in structure.group_ids.items():
        user_ids = await schedule.queries.group_user_ids([group_id])
        head = user_ids[0] if user_ids else None
        await schedule.update_group.execute(
            SYSTEM_ACTOR,
            group_id,
            curator_id=teachers[CURATORS[key]],
            head_student_id=head,
        )
        if user_ids:
            await schedule.assign_subgroups.execute(
                SYSTEM_ACTOR, group_id, split_in_two(user_ids, demo)
            )


def split_in_two(
    user_ids: Sequence[UUID], first: Collection[UUID]
) -> list[tuple[UUID, int | None]]:
    """Students in `first` get subgroup 1; the others alternate 2, 1, 2, ..."""
    pinned: list[tuple[UUID, int | None]] = [(u, 1) for u in user_ids if u in first]
    rest = [u for u in user_ids if u not in first]
    start = 1 if pinned else 0
    return pinned + [(u, 1 + (i + start) % 2) for i, u in enumerate(rest)]
