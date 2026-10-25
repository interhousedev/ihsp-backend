"""The after-commit hook that queues text processing of a file."""

from uuid import UUID

from app.shared.db.uow import AfterCommit
from app.shared.tasks import TaskKicker

PROCESS_TASK = "files.process"


def process_hook(kicker: TaskKicker, file_id: UUID) -> AfterCommit:
    """Return a coroutine function that kicks ``files.process`` for the file."""

    async def hook() -> None:
        await kicker.kick(PROCESS_TASK, file_id=str(file_id))

    return hook
