"""NB-7, NB-32: a saved answer keeps its web citations as readable links."""

from app.modules.notebooks.domain.entities import MessageContent
from app.modules.notebooks.domain.enums import MessageRole
from app.modules.notebooks.wiring_chat import build_chat
from app.shared.actor import Actor
from app.shared.contracts.web_search import WebResult
from tests.factories.notebooks import make_message
from tests.fakes.notebooks.llm import ScriptedLlm
from tests.notebooks.unit.chat.support import notebook_with_source
from tests.notebooks.unit.web.conftest import WebCore


async def test_web_chips_become_links_and_source_chips_stay(
    make_web_core: WebCore, student: Actor, scripted_llm: ScriptedLlm
) -> None:
    """The note has `⟦1⟧` as before and `[site](url)` for the web page."""
    core, _ = make_web_core()
    chat = build_chat(core)
    notebook, _ = await notebook_with_source(core, student)
    scripted_llm.queue_text("Light becomes energy [[S1:P1]] and sugar [[W2]].")
    turn = await chat.ask_notebook.execute(student, notebook.id, "Q?", web_search=True)

    note = await chat.save_note.execute(
        student, notebook.id, turn.assistant_message.id, None
    )

    assert note.body_md == (
        "Light becomes energy ⟦1⟧ and sugar "
        "[school2.example.org](https://school2.example.org/photosynthesis)."
    )
    assert note.title == "Light becomes energy and sugar."
    assert note.citations == turn.assistant_message.content.citations


async def test_a_chip_without_a_stored_result_is_dropped(
    make_web_core: WebCore, student: Actor
) -> None:
    """A web chip whose page is not on the message disappears with its space."""
    core, _ = make_web_core()
    chat = build_chat(core)
    notebook, _ = await notebook_with_source(core, student)
    answer = await make_message(
        core.uow_factory,
        notebook,
        role=MessageRole.ASSISTANT,
        content=MessageContent(
            text="Light ⟦1⟧ makes sugar ⟦w5⟧ and oxygen ⟦w1,9⟧.",
            web=[
                WebResult(
                    n=1,
                    title="Photosynthesis",
                    url="https://school.example.org/photosynthesis",
                    site="school.example.org",
                    snippet="Plants make sugar.",
                    why="Explains the process.",
                    cited=True,
                )
            ],
        ),
    )

    note = await chat.save_note.execute(student, notebook.id, answer.id, None)

    assert note.body_md == (
        "Light ⟦1⟧ makes sugar and oxygen "
        "[school.example.org](https://school.example.org/photosynthesis)."
    )
