"""The MCP/AI block builders know every LMS question type and build valid content."""

from typing import Any

from app.modules.lms.domain.step_content import Question
from app.shared.contracts.lms_blocks import (
    BlankInput,
    BlockInputError,
    PairInput,
    QuestionInput,
    VariableInput,
    build_question,
)

import pytest


def make(**fields: Any) -> QuestionInput:
    return QuestionInput(prompt="p", **fields)


CASES = [
    make(type="sorting", items=["a", "b", "c"]),
    make(
        type="matching",
        pairs=[PairInput(left="a", right="A"), PairInput(left="b", right="B")],
    ),
    make(type="table", rows=["r"], columns=["c1", "c2"], correct_cells=[(0, 1)]),
    make(type="blanks", blanks=[BlankInput(accepted=["x"])]),
    make(
        type="random_number",
        variables=[VariableInput(name="a", min=1, max=5)],
        formula="a*2",
    ),
    make(type="formula", expression="x^2"),
    make(type="code", expected_outputs=["1"]),
    make(type="code"),
    make(type="free"),
]


@pytest.mark.parametrize("question", CASES, ids=lambda q: q.type)
def test_built_questions_are_valid_lms_questions(question: QuestionInput) -> None:
    built = Question.model_validate(build_question(question))
    assert built.type == question.type


def test_table_grid_marks_the_cells() -> None:
    built = build_question(CASES[2])
    assert built["table"]["correct"] == [[False, True]]


@pytest.mark.parametrize(
    "question",
    [
        make(type="sorting", items=["a"]),
        make(type="matching", pairs=[PairInput(left="a", right="b")]),
        make(type="table", rows=["r"], columns=["c"], correct_cells=[(3, 3)]),
        make(type="blanks", blanks=[BlankInput()]),
        make(type="random_number", formula="1"),
        make(type="formula"),
        make(type="table", rows=["r"], columns=["c"], correct_cells=[]),
        make(
            type="random_number",
            variables=[VariableInput(name="a", min=5, max=1)],
            formula="a",
        ),
    ],
    ids=lambda q: q.type,
)
def test_broken_questions_are_refused(question: QuestionInput) -> None:
    with pytest.raises(BlockInputError):
        build_question(question)
