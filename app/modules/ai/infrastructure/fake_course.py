"""Deterministic course plans and lesson drafts for the fake model (course workspaces).

`FakeLlmGateway.complete_json` calls `build_course_document` first; it answers the two
schemas of the course Studio kinds (`nb_course_plan`, `nb_lesson_draft`) with a short,
believable outline or lesson built from the source titles and passages in the prompt,
written in the language the system prompt asks for (en, ru or uz). Without a key the
whole workspace flow (generate, preview, apply) then runs in development and tests.
"""

import re
from collections import defaultdict
from collections.abc import Sequence
from typing import Any, Final

from app.modules.ai.infrastructure.fake_sources import (
    FakePassage,
    document_passages,
    last_user_text,
    message_text,
)
from app.modules.ai.infrastructure.fake_structured import (
    LETTERS,
    clip,
    clip_words,
    first_sentence,
    head_words,
    sentences,
    topic,
    unique,
)

Document = dict[str, Any]

MAX_SECTIONS: Final = 4
MAX_STEPS: Final = 4
DEFAULT_QUESTIONS: Final = 6
DEFAULT_CARDS: Final = 10
MIN_TEXT_CHARS: Final = 400

_LANGUAGE = re.compile(r"Write in (English|Russian|Uzbek)")
_CODES = {"English": "en", "Russian": "ru", "Uzbek": "uz"}
_SOURCE = re.compile(r'<source id="S(\d+)" title="([^"]*)"')
_QUESTIONS = re.compile(r"(\d+) questions that check the lesson")
_CARDS = re.compile(r"(\d+) cards\. Each card holds")

TEXTS: Final = {
    "en": {
        "plan_title": "Course plan: {topic}",
        "plan_summary": "A short course that walks through {topic} step by step.",
        "course_goal": "Explain the main ideas of {topic}",
        "section_goal": "Describe the key facts about {topic}",
        "step_goal": "Explain {topic} in your own words",
        "step_summary": "Covers: {text} Practised with a worked example, checked "
        "with a short test.",
        "goal_heading": "Goal of the lesson",
        "goal_text": "After this lesson you can explain {topic} and give an example.",
        "example_heading": "Worked example",
        "summary_heading": "Summary",
        "lesson_title": "{topic}",
        "question": "What does the material say about {topic}?",
        "explain": "The material says: {text}",
        "key_point": "Key point {n}",
        "key_fact": "Remember this fact about {topic}.",
        "filler": "Option {letter}",
    },
    "ru": {
        "plan_title": "План курса: {topic}",
        "plan_summary": "Короткий курс, шаг за шагом раскрывающий тему «{topic}».",
        "course_goal": "Объяснять основные идеи темы «{topic}»",
        "section_goal": "Описывать ключевые факты по теме «{topic}»",
        "step_goal": "Объяснять тему «{topic}» своими словами",
        "step_summary": "Содержание: {text} Закрепляется разобранным примером, "
        "проверяется коротким тестом.",
        "goal_heading": "Цель урока",
        "goal_text": "После урока вы сможете объяснить тему «{topic}» и привести "
        "пример.",
        "example_heading": "Разобранный пример",
        "summary_heading": "Итог",
        "lesson_title": "{topic}",
        "question": "Что сказано в материале о теме «{topic}»?",
        "explain": "В материале сказано: {text}",
        "key_point": "Ключевой момент {n}",
        "key_fact": "Запомните этот факт о теме «{topic}».",
        "filler": "Вариант {letter}",
    },
    "uz": {
        "plan_title": "Kurs rejasi: {topic}",
        "plan_summary": "«{topic}» mavzusini bosqichma-bosqich ochadigan qisqa kurs.",
        "course_goal": "«{topic}» mavzusining asosiy g'oyalarini tushuntirish",
        "section_goal": "«{topic}» bo'yicha asosiy faktlarni bayon qilish",
        "step_goal": "«{topic}» mavzusini o'z so'zlaringiz bilan tushuntirish",
        "step_summary": "Mazmuni: {text} Misol bilan mustahkamlanadi, qisqa test "
        "bilan tekshiriladi.",
        "goal_heading": "Darsning maqsadi",
        "goal_text": "Darsdan so'ng «{topic}» mavzusini tushuntira olasiz va misol "
        "keltira olasiz.",
        "example_heading": "Yechilgan misol",
        "summary_heading": "Xulosa",
        "lesson_title": "{topic}",
        "question": "Materialda «{topic}» haqida nima deyilgan?",
        "explain": "Materialda aytilishicha: {text}",
        "key_point": "Asosiy nuqta {n}",
        "key_fact": "«{topic}» haqidagi bu faktni eslab qoling.",
        "filler": "Variant {letter}",
    },
}


def _language_of(system: str) -> str:
    """`en`, `ru` or `uz` from the "Write in ..." line of the system prompt."""
    found = _LANGUAGE.search(system)
    return _CODES[found.group(1)] if found else "en"


def _titles(messages: Sequence[dict[str, Any]]) -> dict[int, str]:
    """The titles of the sources in the `<sources>` block, by source number."""
    text = "\n".join(message_text(m) for m in messages)
    return {int(n): title.strip() for n, title in _SOURCE.findall(text)}


def _source_number(passage: FakePassage) -> int:
    """The source number of a labelled passage (0 for an unlabelled one)."""
    match = re.match(r"S(\d+):P", passage.label)
    return int(match.group(1)) if match else 0


def _step_title(passage: FakePassage, taken: set[str]) -> str:
    """A short title from the first words of a passage, unique inside the plan."""
    words = head_words(passage.text, 4) or "Topic"
    title = words[:1].upper() + words[1:]
    candidate, number = title, 2
    while candidate.casefold() in taken:
        candidate, number = f"{title} {number}", number + 1
    taken.add(candidate.casefold())
    return candidate


def build_course_plan(
    passages: Sequence[FakePassage], titles: dict[int, str], language: str
) -> Document:
    """A plan with a section per source (up to four) and a step per passage."""
    text = TEXTS[language]
    groups: dict[int, list[FakePassage]] = defaultdict(list)
    for passage in passages:
        groups[_source_number(passage)].append(passage)
    taken: set[str] = set()
    sections: list[Document] = []
    for number, group in list(groups.items())[:MAX_SECTIONS]:
        title = titles.get(number) or topic(group[0].text)
        steps = [
            {
                "title": _step_title(p, taken),
                "goals": [text["step_goal"].format(topic=head_words(p.text, 3))],
                "summary": text["step_summary"].format(
                    text=clip(first_sentence(p.text), 160)
                ),
                "refs": p.refs,
            }
            for p in group[:MAX_STEPS]
        ]
        sections.append(
            {
                "title": clip(title, 80),
                "goals": [text["section_goal"].format(topic=clip(title, 60))],
                "refs": group[0].refs,
                "steps": steps,
            }
        )
    name = clip(next(iter(titles.values()), topic(passages[0].text)), 80)
    return {
        "title": text["plan_title"].format(topic=name),
        "summary": text["plan_summary"].format(topic=name),
        "goals": [text["course_goal"].format(topic=name)],
        "sections": sections,
    }


def _text_block(passages: Sequence[FakePassage], name: str, language: str) -> Document:
    """The explanation: goal, one chunk per passage, an example and a summary."""
    text = TEXTS[language]
    parts = [
        f"### {text['goal_heading']}",
        text["goal_text"].format(topic=name),
    ]
    for passage in passages[:3]:
        parts += [f"### {topic(passage.text)}", " ".join(sentences(passage.text)[:2])]
    example = passages[-1]
    parts += [f"### {text['example_heading']}", first_sentence(example.text)]
    bullets = [f"- {clip_words(first_sentence(p.text), 18)}" for p in passages[:3]]
    parts += [f"### {text['summary_heading']}", "\n".join(bullets)]
    markdown = "\n\n".join(parts)
    if len(markdown) < MIN_TEXT_CHARS:  # thin sources: say it all in full
        markdown += "\n\n" + "\n\n".join(p.text for p in passages)
    refs = unique([ref for p in passages[:3] for ref in p.refs])
    return {"type": "text", "markdown": markdown, "refs": refs}


def _facts(passages: Sequence[FakePassage]) -> list[tuple[str, FakePassage]]:
    """Distinct sentences of the passages with the passage each comes from."""
    facts: dict[str, tuple[str, FakePassage]] = {}
    for passage in passages:
        for sentence in sentences(passage.text):
            facts.setdefault(sentence.casefold(), (sentence, passage))
    return list(facts.values())


def _cards_block(
    facts: Sequence[tuple[str, FakePassage]], count: int, language: str
) -> Document:
    """One card per fact; short sources are padded with numbered key points."""
    text = TEXTS[language]
    cards = [
        {"front": f"{topic(p.text)} ({n})", "back": clip(sentence, 300)}
        for n, (sentence, p) in enumerate(facts[:count], start=1)
    ]
    while len(cards) < count:
        n = len(cards) + 1
        cards.append(
            {
                "front": text["key_point"].format(n=n),
                "back": text["key_fact"].format(topic=topic(facts[0][1].text)),
            }
        )
    refs = unique([ref for _, p in facts[:count] for ref in p.refs])
    return {"type": "flashcards", "cards": cards, "refs": refs}


def _question(
    n: int, fact: tuple[str, FakePassage], others: list[str], language: str
) -> Document:
    """A single choice question whose right answer is the fact."""
    text = TEXTS[language]
    sentence, passage = fact
    slot = n % len(LETTERS)
    wrong = [o for o in unique(others) if o.casefold() != sentence.casefold()]
    options: list[Document] = []
    for position in range(len(LETTERS)):
        if position == slot:
            options.append({"text": clip(sentence, 200), "correct": True})
        else:
            filler = text["filler"].format(letter=LETTERS[position].upper())
            options.append(
                {"text": clip(wrong.pop(0), 200) if wrong else filler, "correct": False}
            )
    return {
        "type": "single",
        "prompt": f"{text['question'].format(topic=topic(passage.text))} ({n + 1})",
        "explanation": text["explain"].format(text=clip_words(sentence, 40)),
        "options": options,
    }


def _test_block(
    facts: Sequence[tuple[str, FakePassage]], count: int, language: str
) -> Document:
    """Single choice questions, one per fact (facts are reused when few)."""
    sentences_of = [sentence for sentence, _ in facts]
    questions = [
        _question(n, facts[n % len(facts)], sentences_of, language)
        for n in range(count)
    ]
    refs = unique([ref for _, p in facts[:count] for ref in p.refs])
    return {"type": "test", "questions": questions, "refs": refs}


def build_lesson_draft(
    passages: Sequence[FakePassage], task: str, language: str
) -> Document:
    """A lesson of one text block; a test and cards when the task asks for them."""
    name = topic(passages[0].text)
    facts = _facts(passages)
    blocks = [_text_block(passages, name, language)]
    if 'Flash cards block (type "flashcards")' in task:
        count = _number(_CARDS, task, DEFAULT_CARDS)
        blocks.append(_cards_block(facts, count, language))
    if 'Test block (type "test")' in task:
        count = _number(_QUESTIONS, task, DEFAULT_QUESTIONS)
        blocks.append(_test_block(facts, count, language))
    return {"title": clip(name, 80), "blocks": blocks}


def _number(pattern: re.Pattern[str], task: str, default: int) -> int:
    """The count the task asks for, else the default."""
    found = pattern.search(task)
    return int(found.group(1)) if found else default


def build_course_document(
    schema_name: str, messages: Sequence[dict[str, Any]], system: str
) -> Document | None:
    """The fake plan or lesson for a course schema; None for any other schema."""
    if schema_name not in ("nb_course_plan", "nb_lesson_draft"):
        return None
    passages = document_passages(messages)
    language = _language_of(system)
    if schema_name == "nb_course_plan":
        return build_course_plan(passages, _titles(messages), language)
    return build_lesson_draft(passages, last_user_text(messages), language)
