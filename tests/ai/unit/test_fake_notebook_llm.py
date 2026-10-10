"""NB-FAKE: the fake model answers notebook chat and builds valid Studio documents."""

import json
import re
from typing import Any

from app.modules.ai.domain.errors import AiInvalidOutputError
from app.modules.ai.infrastructure.fake_llm import FakeLlmGateway
from app.modules.ai.infrastructure.fake_structured import BUILDERS

import pytest

CHAT_SYSTEM = (
    "You are the notebook assistant of the IHT student platform. A student asks "
    "questions about the study sources inside <sources>. Example: [[S1:P4]]."
)
STUDIO_SYSTEM = "You turn study sources into learning materials for a lyceum student."
BIOLOGY = [
    "Photosynthesis is the process by which plants convert light energy into "
    "chemical energy. It happens in chloroplasts.",
    "The light reactions take place in the thylakoid membranes. They release "
    "oxygen as a by-product.",
    "The Calvin cycle uses carbon dioxide to build glucose. It runs in the stroma.",
]
CELLS = [
    "Cellular respiration releases energy from glucose. It happens in mitochondria.",
    "ATP is the energy currency of the cell. Cells use it for work.",
]
ALL_SCHEMAS = [
    "nb_guide",
    "nb_summary",
    "nb_report",
    "nb_mind_map",
    "nb_flashcards",
    "nb_quiz",
    "nb_data_table",
    "nb_slides",
    "nb_infographic",
]


def block(*sources: list[str], guide: str | None = None) -> str:
    """The <sources> message text, as the notebooks module builds it."""
    parts = ["<sources>"]
    for n, passages in enumerate(sources, start=1):
        parts.append(f'<source id="S{n}" title="Source {n}" kind="file">')
        if guide:
            parts.append(f"<guide>{guide}</guide>")
        parts.append("\n\n".join(f"[S{n}:P{i}] {t}" for i, t in enumerate(passages, 1)))
        parts.append("</source>")
    parts.append("</sources>")
    return "\n".join(parts)


def user(text: str) -> dict[str, Any]:
    """A plain user message."""
    return {"role": "user", "content": text}


def context(*sources: list[str]) -> dict[str, Any]:
    """The cached context message (a list of parts, like the Anthropic layout)."""
    part = {
        "type": "text",
        "text": block(*sources),
        "cache_control": {"type": "ephemeral"},
    }
    return {"role": "user", "content": [part]}


async def chat(fake: FakeLlmGateway, *messages: dict[str, Any]) -> str:
    """The text of a fake chat answer."""
    result = await fake.complete(
        model="m", system=CHAT_SYSTEM, messages=list(messages), tools=[], max_tokens=9
    )
    assert result["tool_calls"] == []
    return str(result["text"])


async def document(
    schema_name: str, *messages: dict[str, Any], fake: FakeLlmGateway | None = None
) -> dict[str, Any]:
    """The data of a fake structured answer."""
    result = await (fake or FakeLlmGateway()).complete_json(
        model="m",
        system=STUDIO_SYSTEM,
        messages=list(messages),
        schema_name=schema_name,
        schema={},
        max_tokens=100,
    )
    data: dict[str, Any] = result["data"]
    return data


def labels_of(*sources: list[str]) -> set[str]:
    """All labels of a block."""
    return {
        f"S{n}:P{i}" for n, s in enumerate(sources, 1) for i in range(1, len(s) + 1)
    }


def words(text: str) -> int:
    """Word count."""
    return len(text.split())


# - - - Chat - - -


async def test_chat_answer_quotes_the_first_passage_with_a_citation_and_followups() -> (
    None
):
    """NB-FAKE: (fake) <first 100 characters of S1:P1> [[S1:P1]] + <followups>."""
    answer = await chat(
        FakeLlmGateway(), context(BIOLOGY, CELLS), user("What is photosynthesis?")
    )

    assert answer == (
        f"(fake) {BIOLOGY[0][:100]} [[S1:P1]]\n"
        '<followups>["First follow-up?","Second follow-up?","Third follow-up?"]'
        "</followups>"
    )


async def test_chat_answer_is_found_in_a_plain_string_context_and_other_systems() -> (
    None
):
    """A <sources> user message is enough, whatever the system prompt says."""
    fake = FakeLlmGateway()

    result = await fake.complete(
        model="m",
        system="Anything",
        messages=[user(block(CELLS)), user("Question?")],
        tools=[],
        max_tokens=9,
    )

    assert result["text"].startswith(f"(fake) {CELLS[0][:100]} [[S1:P1]]")


async def test_an_anchored_question_cites_the_passage_it_names() -> None:
    """The last user message names S2:P2 -> that passage is cited."""
    answer = await chat(
        FakeLlmGateway(),
        context(BIOLOGY, CELLS),
        user("Explain this.\n\n[Note: the student clicked the passage S2:P2]"),
    )

    assert answer.startswith(f"(fake) {CELLS[1][:100]} [[S2:P2]]\n<followups>")


async def test_a_label_that_is_not_in_the_sources_falls_back_to_the_first_passage() -> (
    None
):
    """An unknown anchor label never produces an invalid citation."""
    answer = await chat(FakeLlmGateway(), context(BIOLOGY), user("About S9:P9?"))

    assert "[[S1:P1]]" in answer and "S9:P9" not in answer


async def test_the_first_passage_is_cited_when_s1_p1_is_not_in_the_request() -> None:
    """Retrieval mode can start at another passage."""
    text = (
        '<sources>\n<source id="S1" title="T" kind="note">\n'
        "[S1:P4] Fourth.\n</source>\n</sources>"
    )

    answer = await chat(FakeLlmGateway(), user(text), user("Q?"))

    assert answer.startswith("(fake) Fourth. [[S1:P4]]")


async def test_without_passages_the_sources_do_not_say() -> None:
    """No labels in the prompt -> no citation and empty follow-ups."""
    answer = await chat(FakeLlmGateway(), user("<sources>\n</sources>"), user("Q?"))

    assert answer == "(fake) The sources do not say.\n<followups>[]</followups>"


async def test_the_chat_system_prompt_alone_selects_the_notebook_answer() -> None:
    """Even without <sources> the notebook prompt is not echoed."""
    answer = await chat(FakeLlmGateway(), user("hello"))

    assert answer == "(fake) The sources do not say.\n<followups>[]</followups>"


async def test_a_multi_line_passage_ends_at_the_blank_line_or_the_closing_tag() -> None:
    """A passage may span lines; tags and the next label end it."""
    text = (
        '<sources>\n<source id="S1" title="T" kind="file">\n<guide>g</guide>\n'
        "[S1:P1] Line one\nline two.\n\n[S1:P2] Last one.\n</source>\n</sources>"
    )

    first = await chat(FakeLlmGateway(), user(text), user("Q?"))
    anchored = await chat(FakeLlmGateway(), user(text), user("S1:P2 please"))

    assert first.startswith("(fake) Line one\nline two. [[S1:P1]]")
    assert anchored.startswith("(fake) Last one. [[S1:P2]]")


async def test_other_requests_are_not_affected() -> None:
    """The assistant behaviour (echo, flash cards, homework) is unchanged."""
    fake = FakeLlmGateway()

    echo = await fake.complete(
        model="m", system="s", messages=[user("hello")], tools=[], max_tokens=9
    )

    assert echo["text"] == "(fake) hello"
    assert echo["usage"] == {"input": echo["usage"]["input"], "output": 3, "cached": 0}


async def test_stream_yields_the_same_text_in_small_chunks_then_the_usage() -> None:
    """NB-FAKE: 12-character deltas, a final usage of chars // 4 with cached 0."""
    fake = FakeLlmGateway()
    messages = [context(BIOLOGY), user("What is photosynthesis?")]
    whole = await chat(fake, *messages)

    items = [
        item
        async for item in fake.stream(
            model="m", system=CHAT_SYSTEM, messages=messages, max_tokens=9
        )
    ]

    deltas = [i["delta"] for i in items[:-1]]
    assert "".join(deltas) == whole
    assert all(0 < len(d) <= 12 for d in deltas) and len(deltas) > 3
    usage = items[-1]["usage"]
    assert set(items[-1]) == {"usage"}
    assert usage["output"] == len(whole) // 4 and usage["cached"] == 0
    assert usage["input"] > 0 and usage["cost_micro"] is None


async def test_requests_are_recorded_with_the_provider_and_schema_name() -> None:
    """The tests of the notebooks module inspect what was sent."""
    fake = FakeLlmGateway()
    provider = {"data_collection": "deny", "require_parameters": True}

    await fake.complete_json(
        model="m",
        system=STUDIO_SYSTEM,
        messages=[context(CELLS)],
        schema_name="nb_quiz",
        schema={},
        max_tokens=5,
        provider=provider,
        timeout_seconds=180,
    )

    request = fake.requests[-1]
    assert request["provider"] == provider and request["schema_name"] == "nb_quiz"
    assert request["system"] == STUDIO_SYSTEM


# - - - Documents: common - - -


@pytest.mark.parametrize("schema_name", [*ALL_SCHEMAS, "nb_slides_revise"])
async def test_every_schema_name_has_a_builder(schema_name: str) -> None:
    """The ten names of the notebooks spec are all known."""
    assert schema_name in BUILDERS


@pytest.mark.parametrize("schema_name", ALL_SCHEMAS)
async def test_documents_are_deterministic_and_the_result_carries_text_and_usage(
    schema_name: str,
) -> None:
    """Same prompt -> same document; text is the JSON of data; usage has cost None."""
    messages = [context(BIOLOGY, CELLS), user("Make it")]
    fake = FakeLlmGateway()

    first = await fake.complete_json(
        model="m",
        system=STUDIO_SYSTEM,
        messages=messages,
        schema_name=schema_name,
        schema={},
        max_tokens=9,
    )
    second = await document(schema_name, *messages)

    assert first["data"] == second
    assert first["text"] == json.dumps(first["data"])
    assert set(first["usage"]) == {"input", "output", "cached", "cost_micro"}
    assert first["usage"]["cost_micro"] is None and first["usage"]["cached"] == 0
    assert first["usage"]["output"] == len(first["text"]) // 4


async def test_an_unknown_schema_name_is_an_invalid_output() -> None:
    """Only notebook schemas are served."""
    with pytest.raises(AiInvalidOutputError):
        await document("something_else", context(CELLS))


@pytest.mark.parametrize("schema_name", ALL_SCHEMAS)
async def test_refs_only_name_labels_that_are_in_the_prompt(schema_name: str) -> None:
    """Every ref of every document exists in the <sources> block."""
    data = await document(schema_name, context(BIOLOGY, CELLS), user("Make it"))

    dumped = json.dumps(data)
    groups = re.findall(r'"refs": \[([^\]]*)\]', dumped)
    named = {r.strip().strip('"') for group in groups for r in group.split(",") if r}
    named |= set(re.findall(r"\[\[(S\d+:P\d+)\]\]", data.get("markdown", "")))
    assert named <= labels_of(BIOLOGY, CELLS)
    if schema_name not in ("nb_guide", "nb_summary"):
        assert named  # something is cited


@pytest.mark.parametrize("schema_name", ALL_SCHEMAS)
async def test_without_labels_documents_are_still_built_with_empty_refs(
    schema_name: str,
) -> None:
    """Plain text (or nothing) in the prompt still gives a document, no refs."""
    plain = await document(schema_name, user("Mitochondria make ATP. Cells need it."))
    empty = await document(schema_name, user(""))

    for data in (plain, empty):
        dumped = json.dumps(data)
        assert not re.findall(r'"refs": \[[^\]]', dumped)
        assert "[[" not in dumped
        assert data  # a non-empty document


# - - - Documents: shapes - - -


async def test_guide_follows_the_schema_limits() -> None:
    """§ 3.2.5: 60-120 words, 5-8 topics of 2-5 words, 3 questions."""
    for passages in ([BIOLOGY[0]], BIOLOGY * 5, ["x"]):
        data = await document("nb_guide", user(" ".join(passages)))

        assert set(data) == {"summary", "key_topics", "questions"}
        assert 60 <= words(data["summary"]) <= 120
        assert 5 <= len(data["key_topics"]) <= 8
        assert all(2 <= words(t) <= 5 for t in data["key_topics"])
        assert len(data["questions"]) == 3
        assert len(set(data["key_topics"])) == len(data["key_topics"])


async def test_summary_follows_the_schema_limits() -> None:
    """§ 3.2.6: title 2-6 words from the first passage, emoji, 80-160 words."""
    data = await document("nb_summary", context(BIOLOGY, CELLS), user("Summarize"))

    assert set(data) == {
        "title",
        "emoji",
        "summary",
        "key_topics",
        "suggested_questions",
    }
    assert data["title"].startswith("Photosynthesis is the process")
    assert 2 <= words(data["title"]) <= 6
    assert data["emoji"] == "📘"
    assert 80 <= words(data["summary"]) <= 160
    assert "**" in data["summary"] and "[[" not in data["summary"]
    assert 6 <= len(data["key_topics"]) <= 10
    assert 4 <= len(data["suggested_questions"]) <= 6


async def test_report_has_a_main_idea_and_three_cited_sections() -> None:
    """§ 3.4.1: # title, ## Main idea, three ## sections with [[S1:P1]] markers."""
    data = await document("nb_report", context(BIOLOGY, CELLS), user("Report"))

    markdown = data["markdown"]
    headings = re.findall(r"^(#{1,6}) (.+)$", markdown, re.MULTILINE)
    assert set(data) == {"title", "markdown"}
    assert 200 <= len(markdown) <= 40_000 and len(markdown) >= 250
    assert headings[0][0] == "#" and headings[1] == ("##", "Main idea")
    assert [h[0] for h in headings[2:]] == ["##", "##", "##"]
    bullets = [line for line in markdown.splitlines() if line.startswith("- ")]
    assert bullets and all(re.search(r"\[\[S\d+:P\d+\]\]$", b) for b in bullets)
    assert "[[S1:P1]]" in markdown
    assert "<" not in markdown


async def test_a_tiny_prompt_still_gives_a_long_enough_report() -> None:
    """The length floor holds for one very short passage."""
    data = await document("nb_report", user(block(["Hi."])))

    assert len(data["markdown"]) >= 250
    assert "[[S1:P1]]" in data["markdown"]


async def test_mind_map_is_a_two_level_tree() -> None:
    """§ 3.4.2: one root, up to four children with refs, then a second level."""
    data = await document("nb_mind_map", context(BIOLOGY, CELLS), user("Map"))

    nodes = data["nodes"]
    ids = [n["id"] for n in nodes]
    by_id = {n["id"]: n for n in nodes}
    roots = [n for n in nodes if n["parent_id"] is None]
    assert len(roots) == 1 and len(set(ids)) == len(ids)
    level1 = [n for n in nodes if n["parent_id"] == roots[0]["id"]]
    level2 = [n for n in nodes if by_id[n["parent_id"] or ids[0]] in level1]
    assert len(level1) == 4 and len(level2) == 4
    assert all(n["parent_id"] in by_id for n in nodes if n["parent_id"])
    assert all(n["refs"] for n in nodes if n["parent_id"])
    assert all(len(n["label"]) <= 60 and len(n["note"]) <= 200 for n in nodes)
    assert all(words(n["label"]) <= 6 for n in nodes)


async def test_flashcards_are_clozes_of_the_statements_of_up_to_ten_passages() -> None:
    """§ 3.4.3: the front asks to finish a statement, the back is the statement."""
    many = [f"Fact number {n} is stated here. More text follows." for n in range(12)]
    data = await document("nb_flashcards", context(many), user("Cards"))

    cards = data["cards"]
    assert len(cards) == 10
    assert cards[0]["front"] == "Finish the statement: Fact number 0 …"
    assert cards[0]["back"] == "Fact number 0 is stated here."
    assert cards[0]["refs"] == ["S1:P1"] and cards[0]["id"] == "c1"
    assert cards[0]["hint"].startswith("Demo content")
    assert len({c["front"].casefold() for c in cards}) == 10
    assert all(len(c["front"]) <= 160 and len(c["back"]) <= 300 for c in cards)


async def test_flashcards_keep_the_cards_of_a_flash_card_source() -> None:
    """A `Front: / Back:` source (LMS cards) gives the same cards back, not clozes."""
    text = (
        "Flash cards: 2 cards.\n\nCard 1\nFront: (c)'\nBack: 0\n\n"
        "Card 2\nFront: (sin x)'\nBack: cos x"
    )
    data = await document("nb_flashcards", context([text]), user("Cards"))

    cards = data["cards"]
    assert [(c["front"], c["back"]) for c in cards] == [
        ("(c)'", "0"),
        ("(sin x)'", "cos x"),
    ]
    assert all(c["refs"] == ["S1:P1"] for c in cards)


async def test_flashcard_fronts_stay_unique_when_passages_start_alike() -> None:
    """Dedupe by normalized front would drop cards, so the fake never repeats."""
    same = ["The cell is small. A.", "The cell is big. B.", "The cell is round. C."]
    data = await document("nb_flashcards", context(same), user("Cards"))

    fronts = [c["front"] for c in data["cards"]]
    assert len({f.casefold() for f in fronts}) == 3


async def test_quiz_over_prose_asks_true_false_about_whole_sentences() -> None:
    """§ 3.4.4: up to 10 questions; a sentence cannot give a false option, so t/f."""
    data = await document("nb_quiz", context(BIOLOGY, CELLS), user("Quiz"))

    questions = data["questions"]
    assert len(questions) == 10
    for index, q in enumerate(questions):
        texts = {o["id"]: o["text"] for o in q["options"]}
        assert q["type"] == "true_false" and list(texts) == ["true", "false"]
        assert q["correct"] == ["true"]
        assert q["explanation"] and q["refs"] and q["id"] == f"q{index + 1}"
        assert words(q["explanation"]) <= 60
    assert questions[0]["prompt"] == (
        "True or false: Photosynthesis is the process by which plants convert light "
        "energy into chemical energy."
    )
    assert len({q["prompt"] for q in questions}) == 10  # the handler dedupes prompts


async def test_quiz_with_one_statement_asks_true_false_and_never_pads() -> None:
    """One sentence cannot give distractors: a true/false question, no fillers."""
    data = await document("nb_quiz", context(["Only one sentence."]), user("Quiz"))

    question = data["questions"][0]
    assert question["type"] == "true_false"
    assert question["prompt"] == "True or false: Only one sentence."
    assert [o["id"] for o in question["options"]] == ["true", "false"]
    assert "Option" not in json.dumps(data)


# - - - Documents: the Derivatives 101 regression - - -

DERIVATIVES_LESSON = (
    "# What is a derivative?\n\nThe derivative of a function measures how fast it "
    "changes. For $f(x) = x^2$ the derivative is $f'(x) = 2x$.\n\n"
    "Rules to remember:\n\n- $(c)' = 0$\n- $(x^n)' = n x^{n-1}$\n- $(f + g)' = f' + g'$"
)
DERIVATIVES_TEST = (
    "Test: 2 questions.\n\nQuestion 1 (single choice): What is the derivative of "
    "x^2?\nOptions: a) 2x; b) x; c) x^2; d) 2\n\nQuestion 2 (number): Value of (3x)' "
    "at any x?"
)
DERIVATIVES_CARDS = (
    "Flash cards: 2 cards.\n\nCard 1\nFront: (c)'\nBack: 0\n\nCard 2\nFront: (sin x)'"
    "\nBack: cos x"
)
GARBAGE = (
    "What does the source say about",
    "Option D",
    "Option C",
    "Look at the beginning",
    "Detail:",
    "Q c A",
    "# What is a derivative?",
    "Rules to remember:",
)


def derivatives_context() -> dict[str, Any]:
    """The three LMS step sources of the demo course, as the notebook renders them."""
    return context([DERIVATIVES_LESSON], [DERIVATIVES_TEST], [DERIVATIVES_CARDS])


@pytest.mark.parametrize("schema_name", ALL_SCHEMAS)
async def test_derivatives_documents_hold_no_template_garbage(schema_name: str) -> None:
    """Regression: headings, list markers and card labels never leak into items."""
    data = await document(schema_name, derivatives_context(), user("Make it"))

    dumped = json.dumps(data, ensure_ascii=False)
    for garbage in GARBAGE:
        assert garbage not in dumped, garbage
    assert "$" not in dumped  # math fences are stripped


async def test_derivatives_title_is_the_whole_heading() -> None:
    """Regression: "What is a derivative", not the first three words "What is a"."""
    quiz = await document("nb_quiz", derivatives_context(), user("Quiz"))
    cards = await document("nb_flashcards", derivatives_context(), user("Cards"))
    mind_map = await document("nb_mind_map", derivatives_context(), user("Map"))

    assert quiz["title"] == "What is a derivative: demo quiz"
    assert cards["title"] == "What is a derivative: demo cards"
    assert mind_map["title"] == "What is a derivative: demo mind map"
    assert mind_map["nodes"][0]["label"] == "What is a derivative"
    assert mind_map["nodes"][1]["label"] != "What is a derivative"


async def test_derivatives_quiz_has_one_true_option_and_false_distractors() -> None:
    """Regression: single choice asks for a formula's right side; the rest is false."""
    data = await document("nb_quiz", derivatives_context(), user("Quiz"))

    questions = data["questions"]
    assert len(questions) >= 5
    assert len({q["prompt"] for q in questions}) == len(questions)
    singles = [q for q in questions if q["type"] == "single"]
    assert len(singles) >= 4
    by_prompt = {q["prompt"]: q for q in singles}
    constant = by_prompt["What does (c)' equal?"]
    texts = {o["id"]: o["text"] for o in constant["options"]}
    assert texts[constant["correct"][0]] == "0"
    assert len(constant["correct"]) == 1
    assert set(texts.values()) - {"0"} <= {"n x^{n-1}", "f' + g'", "cos x", "e^x"}
    assert constant["refs"] == ["S1:P1"]
    assert constant["explanation"].startswith("Demo content")
    power = by_prompt["What does (x^n)' equal?"]
    power_texts = {o["id"]: o["text"] for o in power["options"]}
    assert power_texts[power["correct"][0]] == "n x^{n-1}"
    false_items = [q for q in questions if q["correct"] == ["false"]]
    assert false_items and false_items[0]["prompt"].startswith("True or false: (c)' = ")
    assert "= 0" not in false_items[0]["prompt"]
    assert not any(q["prompt"].startswith("True or false: Name the") for q in questions)


def _guide_messages(title: str, text: str) -> list[dict[str, Any]]:
    """The guide prompt as `build_source_guide` sends it (no passage labels)."""
    return [user(f'<source title="{title}">\n{text}\n</source>')]


async def test_derivatives_lesson_guide_is_made_of_whole_phrases() -> None:
    """Regression: topics are headings, labels and formulas; questions are natural."""
    data = await document(
        "nb_guide", *_guide_messages("What is a derivative", DERIVATIVES_LESSON)
    )

    assert data["summary"].startswith(
        "The derivative of a function measures how fast it changes. For f(x) = x^2 "
        "the derivative is f'(x) = 2x. (c)' = 0. (x^n)' = n x^{n-1}."
    )
    assert data["key_topics"][:4] == [
        "What is a derivative",
        "Rules to remember",
        "(c)' = 0",
        "(x^n)' = n x^{n-1}",
    ]
    assert all(2 <= words(t) <= 5 and "#" not in t for t in data["key_topics"])
    assert data["questions"] == [
        "What is a derivative?",
        "What are the rules to remember?",
        "How would you explain that the derivative of a function measures how fast it "
        "changes?",
    ]
    for garbage in (*GARBAGE, "Key topic", "What should I remember about"):
        assert garbage not in json.dumps(data), garbage


async def test_derivatives_test_guide_quotes_the_questions_of_the_test() -> None:
    """Regression: a test-only step is described by its questions, not "Test: 5"."""
    data = await document(
        "nb_guide", *_guide_messages("Check yourself", DERIVATIVES_TEST)
    )

    assert data["summary"].startswith(
        "The source asks: What is the derivative of x^2? Value of (3x)' at any x?"
    )
    assert data["key_topics"][0] == "Check yourself"
    assert data["questions"] == [
        "What is the derivative of x^2?",
        "Value of (3x)' at any x?",
        "What is the main idea of this source?",
    ]
    assert "Test: 2 questions" not in json.dumps(data)


async def test_derivatives_cards_guide_lists_the_cards_as_formulas() -> None:
    """Regression: no "Card 1 Front: … Back" fragments, no "Q:/A:"."""
    data = await document(
        "nb_guide", *_guide_messages("Flash cards", DERIVATIVES_CARDS)
    )

    assert data["summary"].startswith("(c)' — 0. (sin x)' — cos x.")
    assert data["key_topics"][:3] == ["Flash cards", "(c)' = 0", "(sin x)' = cos x"]
    assert data["questions"][:2] == [
        "What does (c)' equal?",
        "What does (sin x)' equal?",
    ]
    assert "Card 1" not in json.dumps(data) and "Front" not in json.dumps(data)


async def test_derivatives_summary_is_built_from_the_guides_and_labelled_demo() -> None:
    """Regression: the overview reads the <guides>; no "Summary:" echo in questions."""
    guides = (
        '<guides>\n<guide n="1" title="What is a derivative">\n'
        "Summary: The derivative of a function measures how fast it changes. "
        "(c)' = 0.\nKey topics: What is a derivative; Rules to remember; (c)' = 0\n"
        "Questions: What is a derivative? | What are the rules to remember?\n</guide>\n"
        '<guide n="2" title="Check yourself">\nSummary: The source asks: What is the '
        "derivative of x^2?\nKey topics: Check yourself; Key facts\n"
        "Questions: What is the derivative of x^2? | What is the derivative of a "
        "constant?\n</guide>\n</guides>"
    )

    data = await document("nb_summary", user(guides))

    assert data["title"] == "What is a derivative" and data["emoji"] == "📘"
    assert data["summary"].startswith(
        "**Demo overview without a language model.** The derivative"
    )
    assert 80 <= words(data["summary"]) <= 160
    sentences = [x.strip() for x in data["summary"].split(". ") if x.strip()]
    assert len(sentences) == len(set(sentences))  # no sentence repeats
    assert data["key_topics"][:5] == [
        "What is a derivative",
        "Rules to remember",
        "(c)' = 0",
        "Check yourself",
        "Key facts",
    ]
    assert data["suggested_questions"] == [
        "What is a derivative?",
        "What are the rules to remember?",
        "What is the derivative of x^2?",
        "What is the derivative of a constant?",
    ]
    dumped = json.dumps(data)
    assert "Summary:" not in dumped and "Key topic " not in dumped


async def test_derivatives_mind_map_uses_whole_phrases_and_is_labelled_demo() -> None:
    """Regression: no "What is the derivative of" fragments; details differ from parents."""  # noqa: E501
    data = await document("nb_mind_map", derivatives_context(), user("Map"))

    nodes = data["nodes"]
    by_id = {n["id"]: n for n in nodes}
    assert data["title"].endswith(": demo mind map")
    assert nodes[0]["note"].startswith("Demo content")
    labels = [n["label"] for n in nodes]
    assert "Rules to remember" in labels and "(c)' — 0" in labels
    assert all(words(label) <= 6 for label in labels)
    assert all(not label.endswith((" of", " the", " a", " is")) for label in labels)
    for node in nodes[1:]:
        parent = by_id[node["parent_id"]]
        assert (
            node["label"].rstrip("?").casefold()
            != parent["label"].rstrip("?").casefold()
        )
        assert node["refs"]


async def test_derivatives_cards_come_from_formulas_and_cards() -> None:
    """Regression: a formula asks for its right side; LMS cards stay cards."""
    data = await document("nb_flashcards", derivatives_context(), user("Cards"))

    pairs = {c["front"]: c["back"] for c in data["cards"]}
    assert pairs["(c)' = ?"] == "(c)' = 0"
    assert pairs["(x^n)' = ?"] == "(x^n)' = n x^{n-1}"
    assert pairs["(c)'"] == "0" and pairs["(sin x)'"] == "cos x"


async def test_documents_are_labelled_as_demo_content() -> None:
    """The fake never passes for a model: titles or notes say "demo"."""
    for schema_name in ("nb_quiz", "nb_flashcards", "nb_mind_map", "nb_report"):
        data = await document(schema_name, derivatives_context(), user("Make it"))

        assert "demo" in json.dumps(data, ensure_ascii=False).casefold(), schema_name


async def test_data_table_has_term_and_definition_columns() -> None:
    """§ 3.4.5: one row per passage up to 10, cells within 120 characters."""
    many = [f"Term{n} is defined as something long. " * 6 for n in range(12)]
    data = await document("nb_data_table", context(many), user("Table"))

    assert [c["key"] for c in data["columns"]] == ["term", "definition"]
    assert all(c["type"] == "text" for c in data["columns"])
    assert len(data["rows"]) == 10
    row = data["rows"][0]
    assert set(row["cells"]) == {"term", "definition"} and row["refs"] == ["S1:P1"]
    assert all(len(v) <= 120 for r in data["rows"] for v in r["cells"].values())


async def test_slides_are_a_title_an_agenda_content_slides_and_a_summary() -> None:
    """§ 3.4.6: the agenda right after the title, ids s1.., refs on content slides."""
    data = await document("nb_slides", context(BIOLOGY, CELLS), user("Slides"))

    slides = data["slides"]
    assert set(data) == {"title", "subtitle", "slides"}
    assert [s["layout"] for s in slides] == [
        "title",
        "agenda",
        "bullets",
        "bullets",
        "bullets",
        "bullets",
        "two_columns",
        "summary",
    ]
    assert [s["id"] for s in slides] == [f"s{n}" for n in range(1, 9)]
    assert slides[0]["bullets"] == [] and slides[0]["refs"] == []
    assert len(slides[1]["bullets"]) >= 2 and slides[1]["refs"] == []
    assert slides[1]["bullets"] == list(dict.fromkeys(s["title"] for s in slides[2:7]))
    assert all(1 <= len(s["bullets"]) <= 5 for s in slides[2:6])
    assert all(words(b) <= 12 for s in slides[2:6] for b in s["bullets"])
    columns = slides[6]
    assert set(columns["left"]) == {"heading", "bullets"}
    assert columns["right"]["bullets"] and columns["refs"]
    assert all(s["notes"] for s in slides)


async def test_slides_revise_returns_only_the_changed_slides_marked_revised() -> None:
    """The JSON embedded in the last user message names the slides to regenerate."""
    deck = await document("nb_slides", context(BIOLOGY), user("Slides"))
    request = {
        "slides": deck["slides"],
        "changes": [
            {"slide_id": "s3", "instruction": "Shorter"},
            {"slide_id": "s6", "instruction": "Add an example"},
        ],
    }
    task = f"Regenerate only the slides in changes.\n\n{json.dumps(request)}\n\nThanks"

    data = await document("nb_slides_revise", context(BIOLOGY), user(task))

    assert set(data) == {"slides"}
    assert [s["id"] for s in data["slides"]] == ["s3", "s6"]
    by_id = {s["id"]: s for s in deck["slides"]}
    for slide in data["slides"]:
        original = by_id[slide["id"]]
        assert slide["title"] == f"{original['title']} (revised)"
        assert slide["layout"] == original["layout"]
    assert not any(s["title"].endswith("(revised)") for s in deck["slides"])


async def test_slides_revise_without_an_embedded_request_returns_no_slides() -> None:
    """Nothing to revise -> an empty but valid document."""
    data = await document("nb_slides_revise", context(BIOLOGY), user("no json here"))

    assert data == {"slides": []}


async def test_infographic_has_six_blocks_of_mixed_types() -> None:
    """§ 3.4.7: block types, short titles and bodies, refs on every block but stats."""
    data = await document("nb_infographic", context(BIOLOGY, CELLS), user("Info"))

    blocks = data["blocks"]
    assert set(data) == {"title", "subtitle", "footer", "blocks"}
    assert len(blocks) == 6
    assert len({b["type"] for b in blocks}) == 6
    assert {b["type"] for b in blocks} <= {
        "stat",
        "steps",
        "comparison",
        "list",
        "timeline",
        "definition",
        "quote",
        "callout",
    }
    assert all(words(b["title"]) <= 6 and b["refs"] for b in blocks)
    for b in blocks:
        for item in b.get("items", []):
            assert words(item["body"]) <= 18
    comparison = next(b for b in blocks if b["type"] == "comparison")
    assert len(comparison["columns"]) == 2
    assert all(c["title"] and c["points"] for c in comparison["columns"])


@pytest.mark.parametrize(
    ("language", "word"),
    [("Russian", "Тема"), ("Uzbek (Latin script)", "Mavzu"), ("English", "Topic")],
)
def test_fake_label_names_follow_the_prompt_language(language: str, word: str) -> None:
    """The auto labels are named in the language the label prompt asks for."""
    from app.modules.ai.infrastructure.fake_structured import build_document

    system = f"Sort sources into topic labels. Write the label names in {language}."
    user = '<sources><source key="s1" title="A"/><source key="s2" title="B"/></sources>'
    document = build_document(
        "nb_labels",
        [{"role": "system", "content": system}, {"role": "user", "content": user}],
    )
    assert [label["name"] for label in document["labels"]] == [f"{word} 1", f"{word} 2"]
