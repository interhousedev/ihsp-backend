"""Programs of an institution proposal: shape, degree, field ids and count."""

from app.modules.admission.domain.catalog_proposals import invalid_field


def _program(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "school": "School of Engineering",
        "name": "Computer Science",
        "degree": "bachelor",
        "field_ids": ["computer_science"],
    }
    base.update(overrides)
    return base


def test_valid_programs_pass() -> None:
    payload = {"programs": [_program(), _program(school=None, degree="master")]}
    assert invalid_field("institution", payload) is None


def test_degree_outside_the_list_is_refused() -> None:
    payload = {"programs": [_program(degree="2plus2")]}
    assert invalid_field("institution", payload) == "programs"


def test_unknown_field_id_is_refused() -> None:
    payload = {"programs": [_program(field_ids=["not_a_field"])]}
    assert invalid_field("institution", payload) == "programs"


def test_more_than_eight_field_ids_is_refused() -> None:
    ids = ["computer_science"] * 9
    payload = {"programs": [_program(field_ids=ids)]}
    assert invalid_field("institution", payload) == "programs"


def test_more_than_sixty_programs_is_refused() -> None:
    payload = {"programs": [_program() for _ in range(61)]}
    assert invalid_field("institution", payload) == "programs"


def test_sixty_programs_pass() -> None:
    payload = {"programs": [_program() for _ in range(60)]}
    assert invalid_field("institution", payload) is None


def test_school_longer_than_120_is_refused() -> None:
    payload = {"programs": [_program(school="s" * 121)]}
    assert invalid_field("institution", payload) == "programs"
