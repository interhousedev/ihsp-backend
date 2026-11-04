"""COPY: Uzbek answers use ʼ (U+02BC), outside code, addresses and maths."""

from app.shared.ai.uzbek import UzbekStream, normalize_answer, normalize_uzbek

import pytest


@pytest.mark.parametrize(
    ("raw", "clean"),
    [
        ("o'quvchi", "oʼquvchi"),
        ("o‘zbek g’oya maʻlumot o`z", "oʼzbek gʼoya maʼlumot oʼz"),
        ("Bo'limlar: oʼquvchi", "Boʼlimlar: oʼquvchi"),
        ("'qoʻshtirnoq' turadi", "'qoʼshtirnoq' turadi"),
        ("`o'z` o'z", "`o'z` oʼz"),
        ("```python\nprint('o'z')\n```\no'z", "```python\nprint('o'z')\n```\noʼz"),
        ("https://e.uz/o'z o'z", "https://e.uz/o'z oʼz"),
        ("$a'b$ o'z", "$a'b$ oʼz"),
        (
            '```openui\nroot = Stack([t])\nt = TextBlock("o\'z")\n```',
            '```openui\nroot = Stack([t])\nt = TextBlock("oʼz")\n```',
        ),
    ],
)
def test_the_letters_are_normalized_outside_protected_text(
    raw: str, clean: str
) -> None:
    """COPY: letters change; code, URLs and formulas stay as written."""
    assert normalize_uzbek(raw) == clean


def test_only_uzbek_answers_change() -> None:
    """COPY: an English answer keeps its apostrophes."""
    english = "The student's answer isn't ready, and that's fine for the table."
    assert normalize_answer(english) == english
    assert normalize_answer("Fanlar boʻyicha o'quvchi baholari") == (
        "Fanlar boʼyicha oʼquvchi baholari"
    )


@pytest.mark.parametrize("size", [1, 2, 5, 1000])
def test_the_stream_agrees_with_the_whole_text(size: int) -> None:
    """COPY: chunk splits never change the letters."""
    text = "Bo'lim o‘z `o'z` https://e.uz/o'z tayyor. Ma'lumot\nyo'q"
    stream = UzbekStream()
    pieces = [text[i : i + size] for i in range(0, len(text), size)]
    out = "".join(stream.feed(p) for p in pieces) + stream.finish()
    assert out == normalize_uzbek(text)


def test_an_answer_that_is_mostly_a_block_is_still_corrected() -> None:
    """COPY: block identifiers do not make an Uzbek answer English."""
    raw = 'Mana:\n```openui\nt = Table(["Bo\'lim uchun"], [["o\'z"]])\n```'
    assert "Boʼlim" in normalize_answer(raw)


def test_text_after_a_block_is_corrected_and_a_block_address_is_kept() -> None:
    """COPY: the closing fence of a block does not open a protected span."""
    raw = '```openui\nl = Link("o\'z", "https://e.uz/o\'z")\n```\n\nBu ko\'rsatilgan'
    out = normalize_uzbek(raw)
    assert out.endswith("Bu koʼrsatilgan")
    assert 'Link("oʼz", "https://e.uz/o\'z")' in out
