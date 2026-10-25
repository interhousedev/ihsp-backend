"""NB-14: quiz and flash card planning: profiles, modes, blueprint, item rules."""

from collections import Counter
from dataclasses import replace

from app.modules.notebooks.domain.artifacts.kinds.quiz import (
    OptionOut,
    _clean_options,
    option_key,
)
from app.modules.notebooks.domain.assessment.blueprint import (
    ItemSpec,
    PlanItemOut,
    build_blueprint,
    plan_message,
    plan_tokens,
    rules_for,
    template_cap,
)
from app.modules.notebooks.domain.assessment.cost import (
    PipelineShape,
    pipeline_estimate,
)
from app.modules.notebooks.domain.assessment.items import (
    batch_task,
    item_key,
    latex_problem,
    option_letter_problem,
    stem_key,
    stimulus_problem,
    unlettered,
    unseen_reference,
    verify_message,
)
from app.modules.notebooks.domain.assessment.modes import (
    MODE_SPECS,
    choose_mode,
    mode_spec,
)
from app.modules.notebooks.domain.assessment.profile import (
    SourceProfile,
    clean_profiles,
    guess_profile,
)
from app.modules.notebooks.domain.language import prompt_language

import pytest

VOCAB = "\n".join(
    [
        "erratic - unpredictable, irregular",
        "candid - frank, honest",
        "benevolent - kind, generous",
        "obscure - not well known",
        "tenacious - persistent",
    ]
)


def vocab_profile() -> SourceProfile:
    return SourceProfile(label="S1", kind="vocabulary_list", domains=["SAT words"])


@pytest.mark.parametrize("count", [1, 7, 10, 23, 81])
def test_blueprint_has_the_exact_count_and_no_template_over_its_cap(
    count: int,
) -> None:
    """NB-14: exactly `count` slots; no template above 30% (or its fair share)."""
    spec = mode_spec("concept_check", [])
    rules = rules_for(
        count=count,
        types=["single", "true_false"],
        spec=spec,
        cards=False,
        difficulty="medium",
        labels=["S1"],
    )

    blueprint = build_blueprint(rules, [vocab_profile()])

    assert len(blueprint) == count
    cap = template_cap(count, len(spec.quiz_templates))
    assert max(Counter(s.template for s in blueprint).values()) <= cap
    assert len({s.id for s in blueprint}) == count
    assert {s.type for s in blueprint} <= {"single", "true_false"}


def test_planner_slots_are_kept_but_capped_and_unknown_templates_dropped() -> None:
    """NB-14: a planner that asks for one template 10 times gets 3 of 10."""
    rules = rules_for(
        count=10,
        types=["single"],
        spec=MODE_SPECS["vocab_test"],
        cards=False,
        difficulty="medium",
        labels=["S1"],
    )
    proposed = [
        PlanItemOut(
            template="synonym",
            domain="words",
            difficulty="hard",
            source="S1",
            focus=f"w{i}",
        )
        for i in range(10)
    ] + [
        PlanItemOut(template="nonsense", domain="", difficulty="", source="", focus="")
    ]

    blueprint = build_blueprint(rules, [vocab_profile()], proposed)

    templates = Counter(s.template for s in blueprint)
    assert len(blueprint) == 10
    assert templates["synonym"] == 3
    assert "nonsense" not in templates
    assert blueprint[0].focus == "w0" and blueprint[0].source == "S1"


def test_vocab_only_source_gives_the_vocab_test_mode() -> None:
    """NB-14: a word list with definitions becomes a vocabulary test."""
    profile = guess_profile("S1", VOCAB)

    mode = choose_mode("auto", None, [profile])

    assert profile.kind == "vocabulary_list"
    assert mode == "vocab_test"


def test_explicit_mode_and_prompt_win_over_the_profile() -> None:
    """NB-14: the requested mode, then the focus text, then the sources."""
    profiles = [vocab_profile()]

    assert choose_mode("formula_recall", None, profiles) == "formula_recall"
    assert choose_mode("auto", "Full SAT mock test", profiles) == "full_mock"


def test_mixed_sources_give_a_topic_test_mixing_their_templates() -> None:
    """NB-14: a word list and a problem set mix both template sets."""
    profiles = [vocab_profile(), SourceProfile(label="S2", kind="problem_set")]

    mode = choose_mode(None, None, profiles)
    spec = mode_spec(mode, profiles)

    assert mode == "topic_test"
    assert "sentence_completion" in spec.quiz_templates
    assert "word_problem" in spec.quiz_templates


def test_profiles_of_unknown_labels_are_dropped() -> None:
    """NB-14: the profile keeps only the selected sources."""
    data = {
        "sources": [
            {
                "label": "S9",
                "kind": "other",
                "subject": "",
                "domains": [],
                "item_pools": [],
                "has_math": False,
                "term_definition_pairs": False,
            }
        ]
    }

    assert clean_profiles(data, ["S1"]) == []


@pytest.mark.parametrize(
    "stem",
    [
        "In the passage on Montaigne, which word best describes the author?",
        "According to the text, what is erratic?",
        "Which word from the SAT vocabulary list means honest?",
        "What does the author note in line 3?",
        "Согласно тексту, что такое клетка?",
    ],
)
def test_a_stem_pointing_at_unseen_text_is_rejected(stem: str) -> None:
    """NB-14: an item may not depend on a passage the student never sees."""
    assert unseen_reference(stem, "") is not None


def test_a_stem_with_its_own_stimulus_may_name_the_passage() -> None:
    """NB-14: with the excerpt in the item, 'the passage' is legitimate."""
    stem = "In the passage, what does 'candid' most nearly mean?"

    assert unseen_reference(stem, "She was candid about her mistakes.") is None
    assert unseen_reference("Which is true? All of the above", "Text.") is not None


def test_self_contained_stems_pass() -> None:
    """NB-14: a full problem in LaTeX is fine."""
    stem = (
        "Line $s$ passes through $(0,0)$ and is parallel to $y = 36x + 6$. "
        "If $s$ passes through $(9, d)$, what is $d$?"
    )

    assert unseen_reference(stem, "") is None


def test_a_slot_that_needs_a_stimulus_rejects_an_item_without_one() -> None:
    """NB-14: reading slots must carry their excerpt (at most 120 words)."""
    spec = build_blueprint(
        rules_for(
            count=1,
            types=["single"],
            spec=MODE_SPECS["reading_test"],
            cards=False,
            difficulty="medium",
            labels=[],
        ),
        [],
    )[0]

    assert spec.stimulus
    assert stimulus_problem(spec, "") is not None
    assert stimulus_problem(spec, "word " * 121) is not None
    assert stimulus_problem(spec, "A short excerpt.") is None


def test_stem_keys_ignore_case_and_punctuation() -> None:
    """NB-14: duplicates are found by normalised stem."""
    assert stem_key("What is  Erratic?") == stem_key("what is erratic")


def test_the_pipeline_estimate_grows_with_the_count_and_the_checks() -> None:
    """NB-14: more items, verification and refills cost more than one call."""
    base = PipelineShape(count=10, batch_size=8, fill_rounds=2, verify=True)

    small = pipeline_estimate(5_000, 1, base)
    big = pipeline_estimate(5_000, 1, replace(base, count=80))
    bare = pipeline_estimate(5_000, 1, replace(base, verify=False, fill_rounds=0))

    assert big > small > bare
    assert small > 5_000 + 10 * 750 * 5  # more than one call of the same size


@pytest.mark.parametrize(
    ("prompt", "mode"),
    [
        ("Biologiya bo'yicha sinov", "concept_check"),
        ("To'liq sinov SAT", "full_mock"),
        ("SAT mock sinov", "full_mock"),
        ("Вопросы по тексту о фотосинтезе", "concept_check"),
        ("Тест на понимание текста", "reading_test"),
        ("Типичные ошибки в задачах", "problem_practice"),
        ("Типичные ошибки студентов", "concept_check"),
        ("Только один тип вопросов", "question_type_test"),
        ("Essay tasks of at least 250 words", "concept_check"),
        ("Test the words from unit 3", "vocab_test"),
        ("So'zlarning ma'nosi bo'yicha test", "vocab_test"),
    ],
)
def test_prompt_modes_need_phrases_not_bare_words(prompt: str, mode: str) -> None:
    assert choose_mode("auto", prompt, []) == mode


def test_a_mixed_mock_asks_for_a_stimulus_only_on_reading_templates() -> None:
    profiles = [
        SourceProfile(label="S1", kind="problem_set", domains=["Algebra"]),
        SourceProfile(label="S2", kind="reading_passages", domains=["Craft"]),
    ]
    spec = mode_spec("full_mock", profiles)
    rules = rules_for(
        count=20,
        types=["single"],
        spec=spec,
        cards=False,
        difficulty="medium",
        labels=["S1", "S2"],
    )
    blueprint = build_blueprint(rules, profiles)
    reading = set(MODE_SPECS["reading_test"].quiz_templates)
    assert any(s.stimulus for s in blueprint)
    assert all(s.stimulus == (s.template in reading) for s in blueprint)


def test_the_plan_budget_fits_a_long_set() -> None:
    assert plan_tokens(10) == 3_000
    assert plan_tokens(60) >= 60 * 70


def test_a_paragraph_number_alone_is_not_an_unseen_reference() -> None:
    stem = "What belongs in body paragraph 1 of an IELTS Task 2 essay?"
    assert unseen_reference(stem, "") is None


def test_a_numbered_paragraph_pointer_is_still_rejected() -> None:
    assert unseen_reference("What is the main idea in paragraph 2?", "") is not None


def test_a_bare_dollar_around_prose_is_rejected() -> None:
    text = "The joining fee is $60 and the monthly fee is $20 per month."
    assert latex_problem(text) is not None
    assert latex_problem(r"The fee is \$60 and then \$20 a month.") is None
    math = r"Total cost is $60 + 20m$ and $\text{rate per month}$."
    assert latex_problem(math) is None


def test_the_solver_is_told_how_to_judge_multiple_answer_items() -> None:
    message = verify_message([{"id": "b4", "type": "multiple"}], cards=False)
    assert "`type` multiple" in message
    assert '"type": "multiple"' in message


def test_math_options_that_differ_only_in_sign_are_distinct() -> None:
    raw = [
        OptionOut(id="a", text="$-3$"),
        OptionOut(id="b", text="$3$"),
        OptionOut(id="c", text="$x = 2$ and $x = 3$"),
        OptionOut(id="d", text="$x = -2$ and $x = -3$"),
    ]
    assert _clean_options(raw) is not None
    assert option_key("Paris.") == option_key("paris")
    assert option_key("$3$") == option_key("$ 3 $")


def test_the_writer_must_not_copy_solved_source_problems() -> None:
    spec = ItemSpec("b1", "single", "direct_computation", "Algebra", "easy", "S1")
    task = batch_task([spec], mode="full_mock", cards=False, prompt=None)
    assert "Never copy a solved problem" in task


def test_the_planner_weights_exam_sections_not_sources() -> None:
    rules = rules_for(
        count=10,
        types=["single"],
        spec=MODE_SPECS["vocab_test"],
        cards=False,
        difficulty="medium",
        labels=["S1"],
    )
    message = plan_message(rules, "full_mock", [vocab_profile()], None)
    assert "weight the exam's sections, not the sources" in message


def test_a_generic_stem_over_another_stimulus_is_not_a_duplicate() -> None:
    stem = "Which choice best states the main idea of the text?"
    assert item_key(stem, "Bees on roofs.") != item_key(stem, "Medieval travel.")
    assert item_key(stem, "Bees on roofs.") == item_key(stem.upper(), "bees on roofs")


@pytest.mark.parametrize(
    "text",
    [
        "Option B forgets to square the sign.",
        "Choice C reverses the sign.",
        "Вариант Б неверен.",
    ],
)
def test_an_explanation_naming_an_option_letter_is_rejected(text: str) -> None:
    assert option_letter_problem(text) is not None


def test_an_explanation_quoting_option_text_passes() -> None:
    assert option_letter_problem("The value 6 comes from not dividing by 2.") is None
    assert option_letter_problem("A choice of a semicolon joins two clauses.") is None


def test_a_lowercase_article_after_answer_is_not_a_letter() -> None:
    assert option_letter_problem("The answer a student gives must be exact.") is None


def test_option_letters_in_an_explanation_become_quoted_option_texts() -> None:
    options = [{"id": "A", "text": "$-3$"}, {"id": "B", "text": "$6$"}]
    text = unlettered("Option A flips the sign; choice B skips the division.", options)
    assert (
        text == "The option «$-3$» flips the sign; the option «$6$» skips the division."
    )
    assert option_letter_problem(text) is None
    assert option_letter_problem(unlettered("Option D is wrong.", options))


def test_punctuation_choices_are_distinct_options() -> None:
    raw = [
        OptionOut(id="a", text="March,"),
        OptionOut(id="b", text="March;"),
        OptionOut(id="c", text="March"),
        OptionOut(id="d", text="March, and"),
    ]
    assert _clean_options(raw) is not None


@pytest.mark.parametrize(
    ("prompt", "language"),
    [
        ("сделай тест по биологии", "ru"),
        ("Биологиядан тест тузинг қисқа", "uz"),
        ("biologiya bo'yicha test tuz", "uz"),
        ("make me a sat test", None),
        ("", None),
    ],
)
def test_a_short_request_tells_its_language(prompt: str, language: str | None) -> None:
    assert prompt_language(prompt) == language
