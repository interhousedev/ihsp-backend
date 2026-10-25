"""STF-9, STF-13: CSV with a BOM and ``;`` as the separator."""

from app.modules.academic.application.classwork.csv_export import percent, render_csv


def test_csv_has_a_bom_semicolons_and_empty_cells_for_none() -> None:
    """Excel opens it with the right encoding and columns."""
    data = render_csv([["Name", "Rate"], ["Abdullaev Aziz", None], ["Karimov; B", 3]])

    assert data.startswith(b"\xef\xbb\xbf")
    assert data.decode("utf-8-sig").splitlines() == [
        "Name;Rate",
        "Abdullaev Aziz;",
        '"Karimov; B";3',
    ]


def test_percent_has_one_decimal_and_empty_for_no_rate() -> None:
    """ACA-12: rate is null when no attendance was taken."""
    assert percent(0.6667) == "66.7"
    assert percent(0.0) == "0.0"
    assert percent(None) == ""
