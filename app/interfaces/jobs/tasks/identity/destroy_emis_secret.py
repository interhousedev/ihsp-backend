"""Task ``identity.destroy_emis_secret``: destroy a deleted account's Vault secret."""

from uuid import UUID

from app.interfaces.jobs.broker import broker
from app.interfaces.jobs.context import get_container


@broker.task(
    task_name="identity.destroy_emis_secret", retry_on_error=True, max_retries=5
)
async def destroy_emis_secret(user_id: UUID) -> None:
    """Delete the secret and all its versions; Vault errors make the task retry."""
    container = get_container()
    await container.identity.emis.destroy_emis_secret.execute(user_id)
