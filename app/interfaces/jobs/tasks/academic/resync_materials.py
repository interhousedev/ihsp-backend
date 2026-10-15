"""Task academic.resync_materials: replace EMIS materials in some terms (admin)."""

from app.bootstrap.container import Container
from app.interfaces.jobs.broker import broker
from app.interfaces.jobs.context import get_container


@broker.task(task_name="academic.resync_materials")
async def resync_materials(terms: list[list[str | int]]) -> int:
    """Purge and download the materials; ``terms`` holds [academic year, half]."""
    container: Container = get_container()
    chosen = [(str(year), int(half)) for year, half in terms]
    return await container.academic.marks.resync_materials.execute(chosen)
