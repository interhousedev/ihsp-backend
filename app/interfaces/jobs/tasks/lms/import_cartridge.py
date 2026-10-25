"""Task `lms.import_cartridge`: create a course from an uploaded .imscc file."""

from uuid import UUID

from app.interfaces.jobs.broker import broker
from app.interfaces.jobs.context import get_container
from app.shared.actor import Actor, Role


@broker.task(task_name="lms.import_cartridge")
async def import_cartridge(
    job_id: str,
    file_id: str,
    user_id: str,
    roles: list[str],
    scopes: list[str] | None = None,
) -> None:
    """Run the import job as the uploader (roles as they were at upload time)."""
    container = get_container()
    actor = Actor(
        user_id=UUID(user_id),
        roles=frozenset(Role(r) for r in roles if r in Role._value2member_map_),
        scopes=frozenset(scopes or ()),
    )
    await container.lms.cartridge.run_import.execute(
        job_id=job_id, file_id=UUID(file_id), actor=actor
    )
