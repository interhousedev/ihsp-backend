"""After-commit hooks that start mail tasks."""

from uuid import UUID

from app.shared.db.uow import AfterCommit
from app.shared.tasks import TaskKicker

PARSE_INBOUND = "mail.parse_inbound"
SEND_OUTBOUND = "mail.send_outbound"


def kick_after_commit(kicker: TaskKicker, task_name: str, mail_id: UUID) -> AfterCommit:
    """Return a hook that enqueues ``task_name`` for the mail."""

    async def hook() -> None:
        await kicker.kick(task_name, mail_id=mail_id)

    return hook
