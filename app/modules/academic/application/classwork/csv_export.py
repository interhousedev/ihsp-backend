"""CSV export: UTF-8 with BOM and ``;`` as the separator (opens in Excel)."""

import csv
import io
from collections.abc import Callable, Sequence
from typing import Any

Translate = Callable[[str], str]


def render_csv(rows: Sequence[Sequence[Any]]) -> bytes:
    """Write rows as CSV bytes; None becomes an empty cell."""
    out = io.StringIO()
    writer = csv.writer(out, delimiter=";", lineterminator="\r\n")
    for row in rows:
        writer.writerow(["" if cell is None else cell for cell in row])
    return out.getvalue().encode("utf-8-sig")


def percent(value: float | None) -> str:
    """Format an absence rate (0..1) as a percentage with one decimal."""
    return "" if value is None else f"{value * 100:.1f}"


def report_rows(report: dict[str, Any], t: Translate) -> list[list[Any]]:
    """Header and rows of an ``AttendanceReport`` for export."""
    header = [
        t("academic-csv-label"),
        t("academic-csv-absences"),
        t("academic-csv-excused"),
        t("academic-csv-lessons"),
        t("academic-csv-rate"),
        t("academic-csv-not-taken"),
    ]
    body = [
        [
            row["label"],
            row["absences"],
            row["excused"],
            row["lessons"],
            percent(row["rate"]),
            row["not_taken"],
        ]
        for row in report["rows"]
    ]
    return [header, *body]


def journal_rows(journal: dict[str, Any], t: Translate) -> list[list[Any]]:
    """Header and rows of a ``Journal`` for export."""
    header = [
        t("academic-csv-last-name"),
        t("academic-csv-first-name"),
        *[
            f"{lesson['date']} {lesson['topic'] or ''}".strip()
            for lesson in journal["lessons"]
        ],
        t("academic-csv-absences"),
        t("academic-csv-semester-mark"),
    ]
    rows = [header]
    for student in journal["students"]:
        cells = []
        for cell in student["cells"]:
            text = " ".join(str(mark) for mark in cell["marks"])
            if cell["absent"]:
                flag = t(
                    "academic-csv-excused-short"
                    if cell["excused"]
                    else "academic-csv-absent"
                )
                text = f"{flag} {text}".strip()
            cells.append(text)
        rows.append(
            [
                student["last_name"],
                student["first_name"],
                *cells,
                student["absences"],
                student["semester_mark"],
            ]
        )
    return rows
