"""Curators, head students and subgroups, set once students are registered."""

from uuid import UUID

from app.bootstrap.container import Container
from app.bootstrap.seed.schedule import Structure
from app.shared.actor import SYSTEM_ACTOR

CURATORS = {"2TN2": "languages", "1TN1": "it"}


async def finish_groups(
    container: Container, structure: Structure, teachers: dict[str, UUID]
) -> None:
    """Curator for each group, the first student as head, students split in two."""
    schedule = container.academic.schedule
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
                SYSTEM_ACTOR,
                group_id,
                [(uid, 1 + index % 2) for index, uid in enumerate(user_ids)],
            )
