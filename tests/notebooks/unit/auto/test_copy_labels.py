"""G12: "Make a copy" keeps the topic labels of the sources."""

from app.modules.notebooks.domain.entities import Notebook
from app.modules.notebooks.domain.labels import LabelOrigin
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.modules.notebooks.wiring_core import NotebooksCore
from app.modules.notebooks.wiring_notebooks import build_notebooks
from app.shared.actor import Actor
from tests.factories.notebooks import make_notebook, make_source
from tests.notebooks.unit.labels.support import store_label, store_link

import pytest


@pytest.fixture
async def original(uow_factory: UowFactory, student: Actor) -> Notebook:
    """A notebook of the student."""
    return await make_notebook(uow_factory, student.user_id, title="Biology")


async def test_the_copy_has_the_labels_and_their_links(
    core: NotebooksCore, uow_factory: UowFactory, student: Actor, original: Notebook
) -> None:
    """G12: new labels (same names, emoji, origin), links on the copied sources."""
    one = await make_source(uow_factory, original, title="One")
    two = await make_source(uow_factory, original, title="Two")
    cells = await store_label(uow_factory, original.id, "Cells", LabelOrigin.AUTO, 1)
    exam = await store_label(uow_factory, original.id, "Exam", LabelOrigin.MANUAL, 2)
    await store_link(uow_factory, one.id, cells.id, LabelOrigin.AUTO)
    await store_link(uow_factory, one.id, exam.id, LabelOrigin.MANUAL)
    await store_link(uow_factory, two.id, exam.id, LabelOrigin.MANUAL)

    copy = await build_notebooks(core).copy_notebook.execute(student, original.id)

    async with uow_factory() as uow:
        copied = await uow.labels.list_for_notebook(copy.id)
        sources = {s.title: s for s in await uow.sources.list_for_notebook(copy.id)}
        kept = await uow.labels.list_for_notebook(original.id)
    by_name = {x.name: x for x in copied}
    assert [(x.name, x.origin, x.position) for x in copied] == [
        ("Cells", LabelOrigin.AUTO, 1),
        ("Exam", LabelOrigin.MANUAL, 2),
    ]
    assert {x.id for x in copied}.isdisjoint({cells.id, exam.id})
    assert sources["One"].label_ids == [by_name["Cells"].id, by_name["Exam"].id]
    assert sources["Two"].label_ids == [by_name["Exam"].id]
    assert [x.source_count for x in kept] == [1, 2]  # the original is untouched


async def test_a_notebook_without_labels_copies_as_before(
    core: NotebooksCore, uow_factory: UowFactory, student: Actor, original: Notebook
) -> None:
    """G12: no labels, no rows."""
    await make_source(uow_factory, original)

    copy = await build_notebooks(core).copy_notebook.execute(student, original.id)

    async with uow_factory() as uow:
        assert await uow.labels.list_for_notebook(copy.id) == []
