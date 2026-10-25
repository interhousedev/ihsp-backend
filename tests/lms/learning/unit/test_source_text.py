"""LMS-17: the readable text of a step for notebook sources; keys for authors only."""

from app.modules.lms.domain.learning.source_text import export_text
from app.modules.lms.domain.step_content import (
    AnswerConfig,
    Blank,
    Card,
    FlashcardsBlock,
    Option,
    Pair,
    Question,
    StepContent,
    TableSpec,
    TestBlock,
)
from tests.lms.learning.builders import (
    cards,
    choice,
    content,
    number_question,
    quiz,
    text_block,
    text_question,
)

import pytest

# The "Derivatives 101" demo course of the seed (app/bootstrap/seed/content.py).
LESSON = (
    "# What is a derivative?\n\n"
    "The derivative of a function measures how fast it changes. For "
    "$f(x) = x^2$ the derivative is $f'(x) = 2x$.\n\n"
    "Rules to remember:\n\n- $(c)' = 0$\n- $(x^n)' = n x^{n-1}$\n"
    "- $(f + g)' = f' + g'$\n"
)


def _single(qid: str, prompt: str, right: str, wrong: list[str]) -> Question:
    options = [Option(id=f"{qid}-0", text=right, correct=True)]
    options += [Option(id=f"{qid}-{n}", text=t) for n, t in enumerate(wrong, 1)]
    return Question(id=qid, type="single", prompt=prompt, options=options)


def derivatives_test() -> TestBlock:
    """The "Check yourself" block of the demo course."""
    return TestBlock(
        id="t",
        questions=[
            _single("q1", "What is the derivative of x^2?", "2x", ["x", "x^2", "2"]),
            _single(
                "q2",
                "What is the derivative of a constant?",
                "0",
                ["1", "the constant", "x"],
            ),
            Question(
                id="q3",
                type="multiple",
                prompt="Which of these are rules of differentiation?",
                explanation="The Pythagorean theorem is geometry, not calculus.",
                options=[
                    Option(id="a", text="Sum rule", correct=True),
                    Option(id="b", text="Product rule", correct=True),
                    Option(id="c", text="Pythagorean rule"),
                ],
            ),
            Question(
                id="q4",
                type="number",
                prompt="Value of (3x)' at any x?",
                answer=AnswerConfig(value=3.0),
            ),
            Question(
                id="q5",
                type="text",
                prompt="Name the derivative of sin x.",
                answer=AnswerConfig(accepted=["cos x", "cos(x)", "cosx"]),
            ),
        ],
    )


def derivatives_cards() -> FlashcardsBlock:
    """The "Flash cards" block of the demo course."""
    return FlashcardsBlock(
        id="f",
        cards=[
            Card(id="1", front="(c)'", back="0"),
            Card(id="2", front="(x^n)'", back="n x^(n-1)"),
            Card(id="3", front="(sin x)'", back="cos x"),
            Card(id="4", front="(e^x)'", back="e^x"),
        ],
    )


# - - - Derivatives 101 - - -


def test_text_step_keeps_its_markdown_with_the_heading_and_formulas() -> None:
    """Headings and `$…$` formulas stay as written (the chunker reads headings)."""
    text, starts = export_text(content("What is a derivative", text_block("t", LESSON)))

    assert text == LESSON.strip() and starts == (0,)
    assert text.startswith("# What is a derivative?\n\nThe derivative of a function")
    assert "$(x^n)' = n x^{n-1}$" in text


def test_test_step_gives_questions_and_options_without_answers_to_students() -> None:
    """The "Check yourself" step is readable; no key, no explanation (LMS-17)."""
    text, starts = export_text(content("Check yourself", derivatives_test()))

    assert starts == (0,)
    assert text == (
        "Test: 5 questions.\n\n"
        "Question 1 (single choice): What is the derivative of x^2?\n"
        "Options: a) 2x; b) x; c) x^2; d) 2\n\n"
        "Question 2 (single choice): What is the derivative of a constant?\n"
        "Options: a) 0; b) 1; c) the constant; d) x\n\n"
        "Question 3 (multiple choice): Which of these are rules of differentiation?\n"
        "Options: a) Sum rule; b) Product rule; c) Pythagorean rule\n\n"
        "Question 4 (number): Value of (3x)' at any x?\n\n"
        "Question 5 (short text): Name the derivative of sin x."
    )
    for secret in ("Correct", "Explanation", "Pythagorean theorem", "cos x", "3.0"):
        assert secret not in text


def test_test_step_with_answers_adds_the_key_and_explanations_for_authors() -> None:
    """The course workspace reads the same questions with their answers."""
    text, _ = export_text(
        content("Check yourself", derivatives_test()), with_answers=True
    )

    assert "Question 1 (single choice): What is the derivative of x^2?\n" in text
    assert "Options: a) 2x; b) x; c) x^2; d) 2\nCorrect answer: a) 2x\n\n" in text
    assert "Correct answer: a) Sum rule; b) Product rule\n" in text
    assert "Explanation: The Pythagorean theorem is geometry, not calculus." in text
    assert "Question 4 (number): Value of (3x)' at any x?\nCorrect answer: 3\n" in text
    assert "Accepted answers: cos x; cos(x); cosx" in text


def test_flash_card_step_gives_labelled_cards() -> None:
    """Each card is `Card n / Front / Back`; formulas are kept verbatim."""
    text, starts = export_text(content("Flash cards", derivatives_cards()))

    assert starts == (0,)
    assert text == (
        "Flash cards: 4 cards.\n\n"
        "Card 1\nFront: (c)'\nBack: 0\n\n"
        "Card 2\nFront: (x^n)'\nBack: n x^(n-1)\n\n"
        "Card 3\nFront: (sin x)'\nBack: cos x\n\n"
        "Card 4\nFront: (e^x)'\nBack: e^x"
    )


# - - - Blocks and offsets - - -


def test_blocks_are_joined_by_a_blank_line_and_offsets_point_at_each() -> None:
    """The offsets allow mapping a passage back to its block."""
    step = content(
        "Cells",
        text_block("t1", "# Cells\n\nThe cell is the unit of life."),
        cards("c1", 2),
        text_block("t2", "Mitochondria make ATP."),
    )

    text, starts = export_text(step)

    assert text == (
        "# Cells\n\nThe cell is the unit of life.\n\n"
        "Flash cards: 2 cards.\n\n"
        "Card 1\nFront: Front 1\nBack: Back 1\n\n"
        "Card 2\nFront: Front 2\nBack: Back 2\n\n"
        "Mitochondria make ATP."
    )
    assert [text[start:].split("\n")[0] for start in starts] == [
        "# Cells",
        "Flash cards: 2 cards.",
        "Mitochondria make ATP.",
    ]


def test_block_starts_point_at_the_first_character_of_each_block() -> None:
    """Every exported block starts exactly where its offset says."""
    step = content("S", text_block("a", "AAA"), text_block("b", "BBBB"), cards("c", 1))

    text, starts = export_text(step)

    assert starts == (0, 5, 11)
    assert text[0:3] == "AAA" and text[5:9] == "BBBB"
    assert text[11:].startswith("Flash cards: 1 card.")


def test_secrets_of_every_question_type_stay_out_of_the_student_text() -> None:
    """LMS-17: keys, accepted answers, regexes and explanations never appear."""
    block = quiz(
        "quiz",
        [
            choice("q1", correct=["b"], explanation="Secret reason one"),
            choice("q2", correct=["a", "c"], multiple=True),
            text_question("q3", accepted=["hidden-answer"], regex="^h.*r$"),
            number_question("q4", value=424242),
        ],
    )

    text, starts = export_text(content("S", text_block("t", "Before."), block))

    assert starts == (0, 9)
    assert text.startswith(
        "Before.\n\nTest: 4 questions.\n\nQuestion 1 (single choice)"
    )
    assert "Options: a) Option a; b) Option b; c) Option c" in text
    for secret in ("Secret reason", "hidden-answer", "424242", "^h.*r$", "Correct"):
        assert secret not in text


def test_a_step_with_an_empty_test_has_no_text() -> None:
    """Nothing to export: empty text and no block offsets."""
    assert export_text(content("S", TestBlock(id="q", questions=[]))) == ("", ())


def test_empty_blocks_are_skipped() -> None:
    """Blank Markdown and flash card blocks without cards add nothing."""
    step = StepContent(
        title="S",
        blocks=[
            text_block("a", "  \n"),
            FlashcardsBlock(id="empty", cards=[]),
            text_block("b", "Real text."),
        ],
    )

    assert export_text(step) == ("Real text.", (0,))


def test_card_text_is_trimmed_and_may_span_lines() -> None:
    """Multi-line cards keep their inner line breaks."""
    block = FlashcardsBlock(
        id="c", cards=[Card(id="1", front=" What?\n(two lines) ", back=" Answer ")]
    )

    text, _ = export_text(StepContent(title="S", blocks=[block]))

    assert (
        text
        == "Flash cards: 1 card.\n\nCard 1\nFront: What?\n(two lines)\nBack: Answer"
    )


# - - - Other question types - - -


@pytest.mark.parametrize("with_answers", [False, True])
def test_sorting_and_matching_halves_are_listed_alphabetically(
    with_answers: bool,
) -> None:
    """The order the student sees reveals nothing; authors get the key too."""
    block = TestBlock(
        id="t",
        questions=[
            Question(
                id="s",
                type="sorting",
                prompt="Order the planets from the Sun.",
                options=[Option(id="1", text="Mercury"), Option(id="2", text="Earth")],
            ),
            Question(
                id="m",
                type="matching",
                prompt="Match the organelle to its job.",
                pairs=[
                    Pair(id="p1", left="Ribosome", right="protein synthesis"),
                    Pair(id="p2", left="Mitochondrion", right="ATP"),
                ],
            ),
        ],
    )

    text, _ = export_text(content("S", block), with_answers=with_answers)

    assert "Question 1 (put in order): Order the planets from the Sun.\n" in text
    assert "Items (in random order): Earth; Mercury" in text
    assert (
        "Left: Ribosome; Mitochondrion\nRight (in random order): ATP; protein synthesis"
        in text
    )
    assert ("Correct order: Mercury; Earth" in text) is with_answers
    assert (
        "Correct pairs: Ribosome — protein synthesis; Mitochondrion — ATP" in text
    ) is with_answers


def test_blanks_table_and_code_questions_show_their_shape_only() -> None:
    """Blanks become ____, tables list rows and columns, code names the language."""
    block = TestBlock(
        id="t",
        questions=[
            Question(
                id="b",
                type="blanks",
                prompt="Water is {{1}} and {{ 2 }}.",
                blanks=[
                    Blank(id="1", accepted=["H2O"]),
                    Blank(id="2", accepted=["wet"]),
                ],
            ),
            Question(
                id="t",
                type="table",
                prompt="Mark the metals.",
                table=TableSpec(
                    rows=["Iron", "Oxygen"],
                    columns=["Metal"],
                    correct=[[True], [False]],
                ),
            ),
            Question(
                id="c",
                type="code",
                prompt="Print hello.",
                code={"language": "python", "expected_outputs": ["hello"]},
            ),
        ],
    )

    student, _ = export_text(content("S", block))
    author, _ = export_text(content("S", block), with_answers=True)

    assert "Question 1 (fill in the blanks): Water is ____ and ____." in student
    assert (
        "Question 2 (table): Mark the metals.\nRows: Iron; Oxygen\nColumns: Metal"
        in student
    )
    assert "Question 3 (code): Print hello.\nLanguage: python" in student
    assert "H2O" not in student and "Expected output" not in student
    assert "Blanks: 1: H2O; 2: wet" in author
    assert "Marked cells: Iron × Metal" in author
    assert "Expected output: hello" in author
