"""LaTeX to Unicode conversion for Telegram messages (AI markdown, math in replies)."""

from app.interfaces.bot.richtext.latex import latex_to_unicode


def test_log_base_subscript_keeps_spaces_around_it() -> None:
    result = latex_to_unicode(" \\log_2 8=3 ")

    assert result.text == "log₂ 8=3"
    assert result.needs_image is False


def test_superscript_digit_is_mapped_to_unicode() -> None:
    assert latex_to_unicode("2^3 = 8").text == "2³ = 8"


def test_simple_fraction_uses_fraction_slash() -> None:
    assert latex_to_unicode("\\frac{1}{2}").text == "1⁄2"


def test_compound_fraction_numerator_is_wrapped_in_parentheses() -> None:
    assert latex_to_unicode("\\frac{x+1}{y}").text == "(x+1)/y"


def test_sqrt_of_single_symbol_has_no_parentheses() -> None:
    assert latex_to_unicode("\\sqrt{x}").text == "√x"


def test_sqrt_of_expression_is_wrapped_in_parentheses() -> None:
    assert latex_to_unicode("\\sqrt{x+1}").text == "√(x+1)"


def test_greek_letters_are_converted() -> None:
    assert latex_to_unicode("\\alpha + \\beta").text == "α + β"


def test_cdot_and_le_are_converted() -> None:
    assert latex_to_unicode("a \\cdot b \\le c").text == "a · b ≤ c"


def test_unmappable_superscript_of_several_symbols_is_parenthesised() -> None:
    assert latex_to_unicode("x^{\\alpha+1}").text == "x^(α+1)"


def test_text_command_keeps_its_content() -> None:
    assert latex_to_unicode("\\text{if} x").text == "if x"


def test_left_and_right_delimiters_are_dropped() -> None:
    assert latex_to_unicode("\\left( x \\right)").text == "( x )"


def test_matrix_environment_needs_image() -> None:
    result = latex_to_unicode("\\begin{pmatrix}1&2\\end{pmatrix}")

    assert result.needs_image is True


def test_big_sum_needs_image_and_keeps_readable_text() -> None:
    result = latex_to_unicode("\\sum_{i=1}^{n} i")

    assert result.needs_image is True
    assert result.text.startswith("∑")


def test_nested_fraction_needs_image() -> None:
    assert latex_to_unicode("\\frac{\\frac{1}{2}}{3}").needs_image is True


def test_unknown_command_needs_image() -> None:
    assert latex_to_unicode("\\foobar{x}").needs_image is True
