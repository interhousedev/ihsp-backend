"""LIB-3: Uzbek search normalisation, Cyrillic and Latin spellings meet on one form."""

from app.shared.text import search_normalize, uz_translit

import pytest
from hypothesis import given
from hypothesis import strategies as st

OKINA = "\u02bb"  # o\u02bb g\u02bb
TUTUQ = "\u02bc"  # ma\u02bcno
APOSTROPHES = [
    "'",
    "\u02bb",
    "\u02bc",
    "\u2018",
    "\u2019",
    "\u201b",
    "`",
    "\u00b4",
    "\u2032",
    "\u02b9",
]


@pytest.mark.parametrize(
    ("cyrillic", "latin"),
    [
        ("ўзбек", f"o{OKINA}zbek"),
        ("ғазал", f"g{OKINA}azal"),
        ("қалам", "qalam"),
        ("ҳаво", "havo"),
        ("шаҳар", "shahar"),
        ("чой", "choy"),
        ("ёш", "yosh"),
        ("юрак", "yurak"),
        ("яхши", "yaxshi"),
        ("маъно", f"ma{TUTUQ}no"),
    ],
)
def test_cyrillic_uzbek_becomes_latin(cyrillic: str, latin: str) -> None:
    """LIB-3: the vectors of the library test plan (11.1)."""
    assert uz_translit(cyrillic) == latin


@pytest.mark.parametrize(
    ("cyrillic", "latin"),
    [
        ("цирк", "tsirk"),
        ("эшик", "eshik"),
        ("жўжа", f"jo{OKINA}ja"),
        ("щётка", "shyotka"),
        ("объект", f"ob{TUTUQ}yekt"),
        ("сентябрь", "sentyabr"),
        ("бизнес", "biznes"),
        ("рыба", "riba"),
    ],
)
def test_the_rest_of_the_alphabet_follows_the_uzbek_latin_table(
    cyrillic: str, latin: str
) -> None:
    """LIB-3: ц is ts, э e, ж j, щ sh, ъ a tutuq, ь is dropped, ы is read as i."""
    assert uz_translit(cyrillic) == latin


@pytest.mark.parametrize(
    ("cyrillic", "latin"),
    [
        ("Европа", "yevropa"),
        ("етти", "yetti"),
        ("мен ва ер", "men va yer"),
        ("уезд", "uyezd"),
        ("шеър", f"she{TUTUQ}r"),
        ("бегона", "begona"),
        ("олтин-ер", "oltin-yer"),
        ("съезд", f"s{TUTUQ}yezd"),
    ],
)
def test_e_is_ye_at_the_start_of_a_word_and_after_a_vowel(
    cyrillic: str, latin: str
) -> None:
    """LIB-3: word-initial е gives ye; after a vowel or a sign too, elsewhere e."""
    assert uz_translit(cyrillic) == latin


def test_upper_case_cyrillic_is_lowered_before_it_is_converted() -> None:
    """LIB-3: the result is lower case; Ў and Е need no special case."""
    assert uz_translit("Ўзбекистон ЕВРОПА") == f"o{OKINA}zbekiston yevropa"


def test_a_letter_typed_as_base_plus_breve_is_read_as_one_letter() -> None:
    """LIB-3: text pulled out of PDFs often has ў as у + U+0306 and ё as е + U+0308."""
    assert uz_translit("ўзбек") == f"o{OKINA}zbek"
    assert uz_translit("ёш") == "yosh"


@pytest.mark.parametrize("mark", APOSTROPHES)
def test_every_apostrophe_after_o_or_g_is_one_okina(mark: str) -> None:
    """LIB-3: o with any apostrophe is one letter (okina), the same for g."""
    assert uz_translit(f"o{mark}zbek") == f"o{OKINA}zbek"
    assert uz_translit(f"G{mark}azal") == f"g{OKINA}azal"
    assert uz_translit(f"TO{mark}G{mark}RI") == f"to{OKINA}g{OKINA}ri"


@pytest.mark.parametrize("mark", APOSTROPHES)
def test_every_other_apostrophe_is_one_tutuq(mark: str) -> None:
    """LIB-3: a tutuq typed with any apostrophe collapses to one character."""
    assert uz_translit(f"ma{mark}no") == f"ma{TUTUQ}no"
    assert uz_translit(f"e{mark}lon") == f"e{TUTUQ}lon"


def test_cyrillic_and_latin_spellings_of_a_word_give_the_same_form() -> None:
    """LIB-3: the Cyrillic word and its Latin spellings give one form."""
    forms = {
        uz_translit(word) for word in ("ўзбек", "o\u02bbzbek", "o'zbek", "O\u2019ZBEK")
    }

    assert forms == {f"o{OKINA}zbek"}


def test_a_hard_sign_after_o_is_the_same_as_a_latin_apostrophe_after_o() -> None:
    """LIB-3: Latin cannot tell o-okina from o-tutuq, so "оъ" meets "o'"."""
    assert uz_translit("тоъ") == uz_translit("to'") == f"to{OKINA}"


def test_digits_punctuation_and_latin_letters_are_kept() -> None:
    """LIB-3: only letters and apostrophes change."""
    assert uz_translit("Grade 10, A-1 (2024)!") == "grade 10, a-1 (2024)!"


def test_runs_of_whitespace_become_one_space() -> None:
    """LIB-3: tabs, new lines and doubled spaces do not separate equal words."""
    assert uz_translit("  ўзбек \t\n тили  ") == f"o{OKINA}zbek tili"


def test_an_empty_text_stays_empty() -> None:
    """LIB-3: nothing in, nothing out."""
    assert uz_translit("") == ""
    assert uz_translit("   ") == ""


@pytest.mark.parametrize("language", ["ru", "en", "RU", "de"])
def test_russian_and_english_text_is_only_lowered_and_tidied(language: str) -> None:
    """LIB-3: the language says ru or en, so Cyrillic and apostrophes stay."""
    text = "  Ёлка  Ўзбек\u2019s   o'zbek \n"

    assert uz_translit(text, language=language) == "ёлка ўзбек\u2019s o'zbek"


def test_russian_text_keeps_its_letters() -> None:
    """LIB-3: "Привет, мир" is not turned into Latin when the item says ru."""
    assert uz_translit("Привет,   Мир", language="ru") == "привет, мир"


@pytest.mark.parametrize("language", ["uz", "UZ", "uz-Cyrl", "uz_Latn"])
def test_uzbek_language_tags_are_all_transliterated(language: str) -> None:
    """LIB-3: a script or region subtag does not switch the conversion off."""
    assert uz_translit("ўзбек", language=language) == f"o{OKINA}zbek"


WORDS = [
    "ўзбек",
    "ғазал",
    "қалам",
    "ҳаво",
    "шаҳар",
    "маъно",
    "Европа",
    "o'zbek",
    "O\u2018ZBEK",
    "ma'no",
    "TO\u2018G\u2018RI",
    "  a   b ",
    "тоъ",
    "сўъзъ",
    "объект",
    "ек",
    "\u02bc\u02bb'",
    "o\u02bb\u02bc",
    "г'ъ",
]


@pytest.mark.parametrize("word", WORDS)
def test_converting_twice_changes_nothing_for_known_words(word: str) -> None:
    """LIB-3: the stored form is stable, so a re-index never drifts."""
    once = uz_translit(word)

    assert uz_translit(once) == once


@given(
    st.text(
        alphabet="абвгдеёжзийклмнопрстуфхцчшщъыьэюяўқғҳАЕЎҒ"
        "abdegijklmnopqrstuvxyzOGE '\u2019\u2018\u02bb\u02bc`-\n",
        max_size=40,
    )
)
def test_converting_twice_changes_nothing_for_any_mix_of_scripts(text: str) -> None:
    """LIB-3: idempotent on Cyrillic, Latin, apostrophes and spaces in any order."""
    once = uz_translit(text)

    assert uz_translit(once) == once


@given(st.text(max_size=40))
def test_russian_pass_through_is_idempotent_too(text: str) -> None:
    """LIB-3: lower-case plus whitespace tidy twice is the same as once."""
    once = uz_translit(text, language="ru")

    assert uz_translit(once, language="ru") == once


def test_search_normalize_converts_uzbek_and_tidies_the_edges() -> None:
    """LIB-3: the index text and the query pass through the same function."""
    assert search_normalize("  Ўзбек   TILI\n") == f"o{OKINA}zbek tili"
    assert search_normalize("O'ZBEK  tili", "uz") == f"o{OKINA}zbek tili"


def test_search_normalize_leaves_russian_and_english_alone() -> None:
    """LIB-3: only Uzbek items are transliterated."""
    assert search_normalize("  Война   и МИР ", "ru") == "война и мир"
    assert search_normalize("  Don't  Panic ", "en") == "don't panic"


def test_search_normalize_is_idempotent() -> None:
    """LIB-3: a normalised query normalises to itself."""
    once = search_normalize("  ЎЗБЕК   o'qish ", "uz")

    assert search_normalize(once, "uz") == once
