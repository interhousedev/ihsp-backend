"""The shared services build over the test fakes and the SQL unit of work."""

from app.modules.notebooks.wiring_core import NotebooksCore
from app.shared.actor import Actor
from tests.factories.notebooks import make_notebook


async def test_core_reads_usage_and_notebooks(
    core: NotebooksCore, student: Actor
) -> None:
    """NB-14: a fresh student has the full budget and an empty running counter."""
    notebook = await make_notebook(core.uow_factory, student.user_id)

    usage = await core.usage.execute(student.user_id)

    assert usage.day.used == 0
    assert usage.generating == 0
    assert (await core.locale.locale_of(student.user_id)) == "en"
    async with core.uow_factory() as uow:
        assert (await uow.notebooks.get(notebook.id)) is not None
