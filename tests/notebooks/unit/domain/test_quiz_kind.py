"""NB-14, NB-17: the quiz kind (§ 3.4.4): options, task, validation, seeded shuffle."""

from typing import Any

from app.modules.notebooks.domain.artifacts.handler import (
    ProcessContext,
    ProcessedOutput,
)
from app.modules.notebooks.domain.artifacts.kinds.quiz import HANDLER
from app.modules.notebooks.domain.errors import InvalidOptionsError, OutputInvalidError
from tests.notebooks.unit.domain.kinds_b_pack import two_source_pack

import pytest

CTX = ProcessContext(pack=two_source_pack(), language="en", seed=7)


def single(n: int, **extra: Any) -> dict[str, Any]:
    """A valid single-choice question whose right answer is option ``a``."""
    return {
        "id": f"x{n}",
        "type": "single",
        "prompt": f"Question number {n} about photosynthesis?",
        "options": [
            {"id": "a", "text": f"Right {n}"},
            {"id": "b", "text": f"Wrong b{n}"},
            {"id": "c", "text": f"Wrong c{n}"},
            {"id": "d", "text": f"Wrong d{n}"},
        ],
        "correct": ["a"],
        "explanation": "Because the sources say so.",
        "hint": "Think",
        "difficulty": "easy",
        "topic": "Light",
        "refs": ["S1:P1"],
        **extra,
    }


def multiple(n: int, **extra: Any) -> dict[str, Any]:
    """A valid multiple-choice question with options ``a`` and ``b`` correct."""
    return single(n, **{"type": "multiple", "correct": ["a", "b"], **extra})


def true_false(n: int, **extra: Any) -> dict[str, Any]:
    """A valid true/false question, ``true`` is right."""
    return {
        **single(n),
        "type": "true_false",
        "options": [
            {"id": "true", "text": "True"},
            {"id": "false", "text": "False"},
        ],
        "correct": ["true"],
        **extra,
    }


def run(
    questions: list[dict[str, Any]],
    ctx: ProcessContext = CTX,
    **options: Any,
) -> ProcessedOutput:
    parsed = HANDLER.parse_options(options)
    return HANDLER.process({"title": "Quiz", "questions": questions}, parsed, ctx)


def texts(question: dict[str, Any]) -> list[str]:
    return [option["text"] for option in question["options"]]


def test_options_defaults_are_filled_in_stored_options() -> None:
    """NB-14: defaults fill in; unset common options are not stored."""
    stored = HANDLER.stored_options(HANDLER.parse_options({}))

    assert stored == {
        "count": "standard",
        "difficulty": "medium",
        "types": ["single", "multiple", "true_false"],
    }


def test_options_keep_language_and_sources() -> None:
    """NB-14: common options are stored as JSON values."""
    source = "00000000-0000-0000-0000-000000000001"

    stored = HANDLER.stored_options(
        HANDLER.parse_options({"language": "uz", "source_ids": [source]})
    )

    assert stored["language"] == "uz"
    assert stored["source_ids"] == [source]


@pytest.mark.parametrize(
    "raw",
    [
        {"count": "huge"},
        {"difficulty": "extreme"},
        {"types": []},
        {"types": ["essay"]},
        {"language": "de"},
        {"source_ids": ["not-a-uuid"]},
    ],
)
def test_invalid_options_raise_with_details(raw: dict[str, Any]) -> None:
    """NB-14: pydantic errors become InvalidOptionsError with a details list."""
    with pytest.raises(InvalidOptionsError) as caught:
        HANDLER.parse_options(raw)

    assert caught.value.params["details"]


def test_repeated_types_are_deduplicated() -> None:
    """NB-14: the order of `types` is kept, repeats are removed."""
    stored = HANDLER.stored_options(
        HANDLER.parse_options({"types": ["single", "single", "true_false"]})
    )

    assert stored["types"] == ["single", "true_false"]


@pytest.mark.parametrize(
    ("count", "tokens"), [("fewer", 2500), ("standard", 4500), ("more", 8000)]
)
def test_max_tokens_follow_the_count(count: str, tokens: int) -> None:
    """NB-14: § 3.4.0 token table."""
    assert HANDLER.max_tokens(HANDLER.parse_options({"count": count})) == tokens


def test_handler_constants() -> None:
    """NB-14: schema name, no report format and an untouched input cap."""
    options = HANDLER.parse_options({})

    assert HANDLER.schema_name == "nb_quiz"
    assert HANDLER.kind.value == "quiz"
    assert HANDLER.report_format(options) is None
    assert HANDLER.input_cap_tokens(150_000) == 150_000
    assert HANDLER.default_title("Biology", options) == "Quiz: Biology"


def test_task_block_names_count_difficulty_and_focus() -> None:
    """NB-14: the task has N, the difficulty clause and the focus text."""
    options = HANDLER.parse_options({"count": "more", "difficulty": "hard"})

    task = HANDLER.task_block(options, "chlorophyll only")

    assert "Create 20 quiz questions" in task
    assert "Difficulty hard: apply and reason across passages." in task
    assert "chlorophyll only" in task
    assert "Mix: mostly single choice" in task
    assert "explanation" in task


def test_task_block_with_a_subset_of_types_names_only_those() -> None:
    """NB-14: a student who asked for true/false only gets no mix sentence."""
    options = HANDLER.parse_options({"types": ["true_false"]})

    task = HANDLER.task_block(options, None)

    assert "Use only these question types: `true_false`" in task
    assert "Mix:" not in task
    assert "focus" not in task


def test_single_question_is_stored_with_numbered_ids() -> None:
    """NB-17: ids become q1..qn and options a, b, c, d."""
    out = run([single(1), single(2)])

    questions = out.content["questions"]
    assert [q["id"] for q in questions] == ["q1", "q2"]
    assert [o["id"] for o in questions[0]["options"]] == ["a", "b", "c", "d"]
    assert out.title == "Quiz"
    assert out.content["title"] == "Quiz"


def test_single_with_two_correct_ids_is_dropped() -> None:
    """NB-17: `single` has exactly one correct id."""
    bad = single(1, correct=["a", "b"])

    out = run([bad, single(2)])

    assert len(out.content["questions"]) == 1


def test_multiple_needs_two_and_fewer_than_all() -> None:
    """NB-17: `multiple` has 2+ correct ids and not all of them."""
    one = multiple(1, correct=["a"])
    every = multiple(2, correct=["a", "b", "c", "d"])

    out = run([one, every, multiple(3)])

    questions = out.content["questions"]
    assert len(questions) == 1
    assert len(questions[0]["correct"]) == 2
    assert questions[0]["type"] == "multiple"


def test_true_false_keeps_true_then_false_and_is_not_shuffled() -> None:
    """NB-17: options of true_false keep ids `true`/`false` in order."""
    swapped = true_false(1)
    swapped["options"] = list(reversed(swapped["options"]))

    out = run([swapped])

    question = out.content["questions"][0]
    assert [o["id"] for o in question["options"]] == ["true", "false"]
    assert question["correct"] == ["true"]


def test_true_false_with_wrong_ids_or_two_correct_is_dropped() -> None:
    """NB-17: options must be exactly true/false with one correct."""
    letters = true_false(
        1, options=[{"id": "a", "text": "Yes"}, {"id": "b", "text": "No"}]
    )
    both = true_false(2, correct=["true", "false"])

    out = run([letters, both, single(3)])

    assert [q["type"] for q in out.content["questions"]] == ["single"]


def test_true_false_with_an_empty_option_text_is_dropped() -> None:
    """NB-17: every option needs a text."""
    blank = true_false(1)
    blank["options"] = [{"id": "true", "text": " "}, {"id": "false", "text": "No"}]

    with pytest.raises(OutputInvalidError):
        run([blank])


def test_unknown_correct_id_drops_the_question() -> None:
    """NB-17: every `correct` id must exist among the options."""
    out = run([single(1, correct=["z"]), single(2)])

    assert len(out.content["questions"]) == 1


@pytest.mark.parametrize("count", [1, 7])
def test_option_count_outside_two_to_six_drops_the_question(count: int) -> None:
    """NB-17: 2 to 6 options."""
    options = [{"id": f"o{i}", "text": f"Option {i}"} for i in range(count)]
    wrong = single(1, options=options, correct=["o0"])

    out = run([wrong, single(2)])

    assert len(out.content["questions"]) == 1


def test_six_options_are_accepted_and_get_letter_ids() -> None:
    """NB-17: six options are the maximum; ids go up to f."""
    options = [{"id": f"o{i}", "text": f"Option {i}"} for i in range(6)]

    out = run([single(1, options=options, correct=["o3"])])

    question = out.content["questions"][0]
    assert [o["id"] for o in question["options"]] == list("abcdef")


def test_duplicate_option_ids_drop_the_question() -> None:
    """NB-17: option ids are unique."""
    clash = single(1)
    clash["options"][1]["id"] = "a"

    out = run([clash, single(2)])

    assert len(out.content["questions"]) == 1


def test_duplicate_prompts_are_removed_after_normalising() -> None:
    """NB-17: same prompt up to case and punctuation counts once."""
    first = single(1, prompt="Which gas is released?")
    again = single(2, prompt="  which GAS is released ")

    out = run([first, again, single(3)])

    assert len(out.content["questions"]) == 2


def test_empty_explanation_drops_the_question() -> None:
    """NB-17: `explanation` is required."""
    out = run([single(1, explanation="  "), single(2)])

    assert len(out.content["questions"]) == 1


def test_long_explanation_is_cut_to_sixty_words() -> None:
    """NB-17: at most 60 words."""
    long = " ".join(f"word{i}" for i in range(90))

    out = run([single(1, explanation=long)])

    assert len(out.content["questions"][0]["explanation"].split()) == 60


def test_question_types_that_were_not_requested_are_dropped() -> None:
    """NB-14: `types` restricts the output."""
    out = run([single(1), true_false(2), multiple(3)], types=["single", "multiple"])

    assert [q["type"] for q in out.content["questions"]] == ["single", "multiple"]


def test_shuffle_is_stable_for_the_same_seed() -> None:
    """NB-17: the same seed gives the same order."""
    questions = [single(n) for n in range(1, 11)]

    first = run(questions, count="standard")
    second = run(questions, count="standard")

    assert first.content == second.content


def test_shuffle_differs_between_seeds_and_moves_the_right_answer() -> None:
    """NB-17: another seed gives another order; `a` is not always right."""
    questions = [single(n) for n in range(1, 11)]

    one = run(questions, ProcessContext(CTX.pack, "en", seed=1))
    two = run(questions, ProcessContext(CTX.pack, "en", seed=2))

    orders_one = [texts(q) for q in one.content["questions"]]
    orders_two = [texts(q) for q in two.content["questions"]]
    assert orders_one != orders_two
    answers = {q["correct"][0] for q in one.content["questions"]}
    assert len(answers) > 1


def test_correct_ids_follow_the_shuffled_options() -> None:
    """NB-17: after the shuffle `correct` still points to the right texts."""
    out = run([single(n) for n in range(1, 8)] + [multiple(8)])

    for number, question in enumerate(out.content["questions"], start=1):
        by_id = {o["id"]: o["text"] for o in question["options"]}
        shown = [by_id[i] for i in question["correct"]]
        expected = [f"Right {number}"]
        if question["type"] == "multiple":
            expected.append(f"Wrong b{number}")
        assert sorted(shown) == sorted(expected)
        assert question["correct"] == sorted(question["correct"])


def test_hint_and_topic_become_none_and_difficulty_defaults_to_the_request() -> None:
    """NB-17: empty hint/topic are None; a missing difficulty is the requested one."""
    plain = single(1, hint="  ", topic="", difficulty=None)

    out = run([plain], difficulty="hard")

    question = out.content["questions"][0]
    assert question["hint"] is None
    assert question["topic"] is None
    assert question["difficulty"] == "hard"


def test_a_difficulty_given_by_the_model_is_kept() -> None:
    """NB-17: per-question difficulty from the model stays."""
    out = run([single(1, difficulty="easy")], difficulty="hard")

    assert out.content["questions"][0]["difficulty"] == "easy"


def test_refs_are_resolved_into_the_refs_index() -> None:
    """NB-17: valid labels stay, invalid are removed, the index is built."""
    question = single(1, refs=["S1:P2", "S9:P9", "[S2:P1]", "S1:P2"])

    out = run([question])

    assert out.content["questions"][0]["refs"] == ["S1:P2", "S2:P1"]
    assert set(out.refs_index) == {"S1:P2", "S2:P1"}
    entry = out.refs_index["S2:P1"]
    assert entry["source_title"] == "Lesson notes"
    assert entry["source_kind"] == "file"
    assert entry["page"] == 1
    assert entry["snippet"] == "Notes on stomata and gas exchange."
    assert entry["passage_id"] == str(CTX.pack.labels["S2:P1"].passage_id)


def test_questions_without_valid_refs_are_dropped_when_enough_remain() -> None:
    """NB-17: keep_items_with_refs with requested = N."""
    questions = [single(n) for n in range(1, 5)] + [single(5, refs=["S9:P9"])]

    out = run(questions, count="fewer")

    assert len(out.content["questions"]) == 4


def test_questions_with_weak_refs_are_kept_when_the_sources_are_thin() -> None:
    """NB-17: fewer than half with refs -> all kept (a result beats an empty one)."""
    questions = [single(1), single(2)] + [single(n, refs=[]) for n in range(3, 6)]

    out = run(questions, count="fewer")

    assert len(out.content["questions"]) == 5
    assert out.content["questions"][4]["refs"] == []


def test_extra_questions_are_truncated_to_the_requested_count() -> None:
    """NB-14: at most N questions."""
    out = run([single(n) for n in range(1, 9)], count="fewer")

    assert len(out.content["questions"]) == 5


def test_ids_are_numbered_after_questions_were_dropped() -> None:
    """NB-17: q1..qn without gaps."""
    out = run([single(1, correct=["z"]), single(2), single(3)])

    assert [q["id"] for q in out.content["questions"]] == ["q1", "q2"]


def test_no_valid_question_is_an_invalid_output_with_problems() -> None:
    """NB-17: fewer than one valid question -> OutputInvalidError."""
    with pytest.raises(OutputInvalidError) as caught:
        run([single(1, correct=["z"]), {"type": "single"}])

    assert any("question 1" in p for p in caught.value.problems)
    assert any("question 2" in p for p in caught.value.problems)


@pytest.mark.parametrize("bad", [None, "text", {"a": 1}])
def test_questions_must_be_a_list(bad: Any) -> None:
    """NB-17: a document without a questions list is invalid."""
    with pytest.raises(OutputInvalidError):
        HANDLER.process(
            {"title": "x", "questions": bad}, HANDLER.parse_options({}), CTX
        )


def test_problems_do_not_echo_the_model_text() -> None:
    """NB-17: problems feed the repair call but never carry the question text."""
    secret = single(1, type="essay", prompt="TOP SECRET PASSAGE TEXT")

    with pytest.raises(OutputInvalidError) as caught:
        run([secret])

    assert "SECRET" not in " ".join(caught.value.problems)


def test_missing_title_falls_back_to_the_first_source() -> None:
    """NB-17: no title from the model -> the first source's title."""
    options = HANDLER.parse_options({})

    out = HANDLER.process({"questions": [single(1)]}, options, CTX)

    assert out.title == "Biology 10.pdf"


def test_long_texts_are_capped() -> None:
    """NB-17: prompt and option texts are capped."""
    question = single(1, prompt="p" * 900)
    question["options"][0]["text"] = "o" * 900

    out = run([question])

    stored = out.content["questions"][0]
    assert len(stored["prompt"]) <= 400
    assert all(len(o["text"]) <= 200 for o in stored["options"])
