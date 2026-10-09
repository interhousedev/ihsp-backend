"""NB-14: question vectors are cached as base64 half floats."""

from app.modules.vectors.domain.packing import pack, unpack


def test_a_vector_survives_the_round_trip_to_half_precision() -> None:
    """Values come back within half-float rounding."""
    values = [0.0, 1.0, -0.5, 0.123456, 3.1415926]

    back = unpack(pack(values))

    assert len(back) == len(values)
    assert all(abs(a - b) < 0.002 for a, b in zip(values, back, strict=True))


def test_a_1024_dimension_vector_is_2_7_kilobytes_of_text() -> None:
    """2 bytes per number, base64."""
    assert len(pack([0.1] * 1024)) == 2732


def test_an_empty_vector_is_an_empty_string() -> None:
    """Edge case: nothing to store."""
    assert pack([]) == ""
    assert unpack("") == []
