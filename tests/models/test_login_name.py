"""Login names: surname.name in lowercase Latin (README -> Models -> User)."""

from app.modules.identity.domain.login_name import base_login, next_free


def test_login_is_surname_dot_name_in_lowercase() -> None:
    assert base_login("BRASTILOV", "ALEKSEY") == "brastilov.aleksey"


def test_cyrillic_names_are_transliterated() -> None:
    assert base_login("Кластер", "Ёлка") == "klaster.yolka"


def test_hyphens_and_spaces_are_removed() -> None:
    assert base_login("Abdul-Karim", "Mary Ann") == "abdulkarim.maryann"


def test_free_login_is_kept() -> None:
    assert next_free("brastilov.aleksey", set()) == "brastilov.aleksey"


def test_taken_login_gets_the_number_two() -> None:
    assert next_free("brastilov.aleksey", {"brastilov.aleksey"}) == (
        "brastilov.aleksey2"
    )


def test_numbers_keep_growing_until_a_free_one_is_found() -> None:
    taken = {"brastilov.aleksey", "brastilov.aleksey2", "brastilov.aleksey3"}

    assert next_free("brastilov.aleksey", taken) == "brastilov.aleksey4"
