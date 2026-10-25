"""The assistant's notebook search finds passages of stored file sources (SQL)."""

from app.modules.notebooks.application.public_api import NotebooksQueriesImpl
from app.modules.notebooks.domain.enums import SourceKind
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.shared.actor import Actor
from tests.factories.notebooks import make_notebook, make_source

JADIDS_RU = (
    "Мунаввар кори Абдурашидханов открыл в Ташкенте школу нового метода "
    "и издавал газету «Хуршид»."
)
OTHER_RU = "Амир Тимур основал державу со столицей в Самарканде."


async def test_search_returns_passages_of_a_file_source(
    uow_factory: UowFactory, student: Actor
) -> None:
    """A lesson file's extracted text is searched by passage, not by its title."""
    notebook = await make_notebook(uow_factory, student.user_id)
    pdf = await make_source(
        uow_factory,
        notebook,
        kind=SourceKind.LESSON_RESOURCE,
        title="lesson-12.pdf",
        texts=(OTHER_RU, JADIDS_RU),
    )
    api = NotebooksQueriesImpl(uow_factory, None)  # type: ignore[arg-type]

    rows = await api.search(student.user_id, notebook.id, "Абдурашидханов школа", 5)

    assert [r["source_title"] for r in rows] == ["lesson-12.pdf"]
    assert rows[0]["source_id"] == str(pdf.id)
    assert "Хуршид" in rows[0]["text"]
