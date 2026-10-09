"""Step types beyond choice/text/number: grading, answers, variants and render."""

from typing import Any
from uuid import UUID

from app.modules.lms.domain.learning.answers import normalize_answers
from app.modules.lms.domain.learning.errors import AnswerInvalidError
from app.modules.lms.domain.learning.expression import ExpressionError, evaluate
from app.modules.lms.domain.learning.grading import correct_answer_of, is_correct
from app.modules.lms.domain.learning.variant import Variant, build_variant
from app.modules.lms.domain.step_content import (
    Blank,
    CodeSpec,
    FormulaSpec,
    Option,
    Pair,
    Question,
    RandomSpec,
    StepContent,
    TableSpec,
    TestBlock,
    VideoBlock,
    Variable,
    assign_ids,
)
from app.modules.lms.domain.student_render import render_questions, render_step

import pytest
from pydantic import ValidationError

ATTEMPT = UUID("12345678-1234-5678-1234-567812345678")


def make(type_: Any, **fields: Any) -> Question:
    """A question `q` of the given type."""
    return Question(id="q", type=type_, prompt="p", **fields)


def test_sorting_needs_exact_order() -> None:
    q = make("sorting", options=[Option(id=i, text=i) for i in "abc"])
    assert is_correct(q, {"option_ids": ["a", "b", "c"]})
    assert not is_correct(q, {"option_ids": ["b", "a", "c"]})
    assert not is_correct(q, {"option_ids": ["a", "b"]})


def test_sorting_is_always_shuffled_in_the_variant() -> None:
    q = make("sorting", options=[Option(id=i, text=i) for i in "abcdef"])
    test = TestBlock(id="t", questions=[q])
    order = build_variant(test, ATTEMPT).option_order["q"]
    assert sorted(order) == list("abcdef") and order != list("abcdef")


def test_matching() -> None:
    q = make(
        "matching",
        pairs=[Pair(id="1", left="a", right="A"), Pair(id="2", left="b", right="B")],
    )
    assert is_correct(q, {"pairs": {"1": "1", "2": "2"}})
    assert not is_correct(q, {"pairs": {"1": "2", "2": "1"}})
    assert not is_correct(q, {"pairs": {"1": "1"}})
    assert correct_answer_of(q, Variant(("q",), {})) == {"pairs": {"1": "1", "2": "2"}}


def test_matching_render_shuffles_rights_and_hides_answer() -> None:
    pairs = [Pair(id=str(i), left=f"l{i}", right=f"r{i}") for i in range(6)]
    test = TestBlock(id="t", questions=[make("matching", pairs=pairs)])
    variant = build_variant(test, ATTEMPT)
    item = render_questions(test, ["q"], variant.option_order)[0]
    assert [x["id"] for x in item["lefts"]] == [str(i) for i in range(6)]
    assert {x["id"] for x in item["rights"]} == {str(i) for i in range(6)}
    assert "right" not in str(item["lefts"])


def test_table() -> None:
    table = TableSpec(
        rows=["r0", "r1"], columns=["c0", "c1"], correct=[[True, False], [False, True]]
    )
    q = make("table", table=table)
    assert is_correct(q, {"cells": ["0:0", "1:1"]})
    assert not is_correct(q, {"cells": ["0:0"]})
    assert not is_correct(q, {"cells": ["0:0", "1:1", "0:1"]})


def test_table_shape_is_validated() -> None:
    with pytest.raises(ValidationError):
        TableSpec(rows=["r"], columns=["a", "b"], correct=[[True]])


def test_blanks() -> None:
    q = make(
        "blanks",
        blanks=[Blank(accepted=["Paris", "paris!"]), Blank(regex=r"\d{4}")],
    )
    assert is_correct(q, {"texts": ["paris", "1999"]})
    assert not is_correct(q, {"texts": ["rome", "1999"]})
    assert not is_correct(q, {"texts": ["paris"]})
    assert not is_correct(q, {"texts": ["paris", "99"]})


def test_text_exact_and_regex_still_work() -> None:
    from tests.lms.learning.builders import text_question

    assert is_correct(text_question("q", accepted=["x"]), {"text": " X "})


def random_question() -> Question:
    spec = RandomSpec(
        variables=[
            Variable(name="a", min=2, max=9),
            Variable(name="b", min=1, max=5, integer=False),
        ],
        formula="a * b + 1",
        tolerance=0.01,
    )
    return Question(id="q", type="random_number", prompt="{a} times {b}?", random=spec)


def test_random_number_is_seeded_and_graded_against_the_variant() -> None:
    q = random_question()
    test = TestBlock(id="t", questions=[q])
    first = build_variant(test, ATTEMPT)
    assert build_variant(test, ATTEMPT).params == first.params
    other = build_variant(test, UUID(int=7)).params
    assert set(other["q"]) == {"a", "b"}
    values = first.params["q"]
    right = values["a"] * values["b"] + 1
    assert is_correct(q, {"number": right}, values)
    assert is_correct(q, {"number": right + 0.005}, values)
    assert not is_correct(q, {"number": right + 1}, values)
    assert correct_answer_of(q, first) == {"number": pytest.approx(right)}
    prompt = render_questions(test, ["q"], first.option_order, first.params)[0][
        "prompt"
    ]
    assert "{a}" not in prompt and f"{values['a']:g}" in prompt


def test_variant_params_roundtrip_and_old_variants_load() -> None:
    variant = Variant(("q",), {}, {"q": {"a": 3.0}})
    assert Variant.from_json(variant.to_json()) == variant
    assert Variant.from_json({"question_ids": ["q"], "option_order": {}}).params == {}


def test_random_variable_range_is_validated() -> None:
    with pytest.raises(ValidationError):
        Variable(name="a", min=5, max=1)
    with pytest.raises(ValidationError):
        RandomSpec(variables=[Variable(name="a", min=1, max=2)] * 2)


def formula(mode: str = "symbolic") -> Question:
    return make(
        "formula", formula=FormulaSpec(expression="(x+1)^2", variables=["x"], mode=mode)
    )


def test_formula_symbolic_accepts_equivalent_forms() -> None:
    q = formula()
    assert is_correct(q, {"text": "x^2 + 2*x + 1"})
    assert is_correct(q, {"text": "(1+x)*(x+1)"})
    assert not is_correct(q, {"text": "x^2 + 1"})
    assert not is_correct(q, {"text": "x +"})
    assert not is_correct(q, {"text": "__import__('os')"})


def test_formula_numeric_mode() -> None:
    q = formula("numeric")
    assert is_correct(q, {"text": "x*x+2*x+1"})
    assert not is_correct(q, {"text": "x*y"})


def test_expression_is_safe() -> None:
    assert evaluate("sqrt(16) + 2^3 + pi*0") == 12
    for bad in ("__import__('os')", "x.y", "9**9**9", "1/0", "(1).real", ""):
        with pytest.raises(ExpressionError):
            evaluate(bad, {"x": 1})


def test_code_compares_output_or_waits_for_review() -> None:
    auto = make("code", code=CodeSpec(expected_outputs=["1\n2"]))
    assert is_correct(auto, {"text": "print", "output": "1  \r\n2\n"})
    assert not is_correct(auto, {"text": "print", "output": "1 2"})
    manual = make("code", code=CodeSpec())
    assert not is_correct(manual, {"text": "print(1)", "output": "1"})


def test_free_answer_is_never_auto_correct() -> None:
    assert not is_correct(make("free"), {"text": "an essay"})


def test_answers_are_validated() -> None:
    sort = make("sorting", options=[Option(id=i, text=i) for i in "ab"])
    pairs = make("matching", pairs=[Pair(id="1", left="a", right="b")])
    table = make("table", table=TableSpec(rows=["r"], columns=["c"], correct=[[True]]))
    blanks = make("blanks", blanks=[Blank(accepted=["x"])])
    test = TestBlock(id="t", questions=[sort, pairs, table, blanks])
    variant = Variant(("q",), {})
    cases: list[tuple[Question, dict[str, Any], dict[str, Any]]] = [
        (sort, {"option_ids": ["b", "a"]}, {"option_ids": ["zz"]}),
        (pairs, {"pairs": {"1": "1"}}, {"pairs": {"1": "9"}}),
        (table, {"cells": ["0:0"]}, {"cells": ["3:3"]}),
        (blanks, {"texts": ["x"]}, {"texts": ["x", "y"]}),
    ]
    for question, good, bad in cases:
        single = TestBlock(id="t", questions=[question])
        assert normalize_answers(single, variant, {"q": good}) == {"q": good}
        with pytest.raises(AnswerInvalidError):
            normalize_answers(single, variant, {"q": bad})
    assert test.questions


def test_video_block_renders_and_ids_are_assigned() -> None:
    content = StepContent(
        title="s",
        blocks=[
            VideoBlock(url="https://youtu.be/x", caption="c"),
            TestBlock(
                questions=[
                    make("matching", pairs=[Pair(left="a", right="b")]).model_copy(
                        update={"id": ""}
                    ),
                    make("blanks", blanks=[Blank(accepted=["x"])]).model_copy(
                        update={"id": ""}
                    ),
                ]
            ),
        ],
    )
    saved = assign_ids(content, set())
    video = render_step(saved, revision_id="r")["blocks"][0]
    assert video["type"] == "video" and video["url"] == "https://youtu.be/x"
    test = saved.blocks[1]
    assert isinstance(test, TestBlock)
    assert test.questions[0].pairs and test.questions[0].pairs[0].id
    assert test.questions[1].blanks and test.questions[1].blanks[0].id


def test_old_content_still_loads() -> None:
    raw = {"title": "s", "blocks": [{"id": "b", "type": "text", "markdown": "m"}]}
    assert StepContent.model_validate(raw).blocks[0].type == "text"
