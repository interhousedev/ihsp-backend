"""AI-EFF-1, AI-OPENUI: the author's tail and its narration guard."""

from app.modules.ai.domain.prompts_author import author_language_line
from app.shared.ai.answer_language import language_line
from app.shared.ai.narration import strip_narration
from app.shared.ai.prompt_cache import split_system
from tests.ai.author_support import arrange
from tests.ai.conftest import AiHarness
from tests.fakes.ai.llm import text_reply

import pytest


def test_only_uzbek_gets_the_letters_rule() -> None:
    """COPY: the rule costs nothing for the other languages."""
    assert "U+02BC" in language_line("uz")
    assert "U+02BC" not in language_line("ru")
    assert "U+02BC" in author_language_line("uz")


async def test_the_course_and_the_language_follow_the_cache_mark(h: AiHarness) -> None:
    """AI-EFF-1: the author's stable part holds no course and no language."""
    author = arrange(h)
    chat = await author.chat()
    h.llm.push(text_reply("a"), text_reply("b"))
    await author.say(chat.id, "Покажи план курса")
    await author.say(chat.id, "Show the plan")
    first, second = (split_system(r["system"]) for r in h.llm.requests)
    assert first[0] == second[0]
    assert "Calculus" not in first[0] and "Calculus" in first[1]
    assert "Russian" in first[1].splitlines()[-1]


async def test_an_author_answer_drops_a_note_about_the_teacher(h: AiHarness) -> None:
    """AI-OPENUI: the narration guard covers the author assistant."""
    author = arrange(h)
    chat = await author.chat()
    h.llm.push(text_reply("The teacher asks for a table. Here it is."))
    result = await author.say(chat.id, "Table")
    assert result.new_messages[-1].text == "Here it is."


@pytest.mark.parametrize(
    "text",
    ["The teacher marks the tests on Friday.", "Учитель объяснил тему на уроке."],
)
def test_a_teacher_as_the_topic_stays(text: str) -> None:
    """AI-OPENUI: the teacher pattern needs a note about the request."""
    assert strip_narration(text, about_student=False) == text


@pytest.mark.parametrize(
    ("raw", "clean"),
    [
        ("I'll look up the fee for you. It is 5.", "It is 5."),
        ("Сейчас проверю стоимость обучения. Она равна 5.", "Она равна 5."),
        ("Посчитаю средние. Итог: 4.", "Итог: 4."),
    ],
)
def test_a_note_about_what_comes_next_is_removed(raw: str, clean: str) -> None:
    """AI-OPENUI: a promise to look something up is not an answer."""
    assert strip_narration(raw) == clean


@pytest.mark.parametrize("text", ["Сейчас 10 часов.", "I will miss you. Bye."])
def test_a_sentence_with_the_same_first_word_stays(text: str) -> None:
    """AI-OPENUI: the pattern needs the verb of a look-up."""
    assert strip_narration(text) == text
