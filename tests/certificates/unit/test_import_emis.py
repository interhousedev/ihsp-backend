"""Import of CEFR and national certificates from EMIS."""

import datetime as dt

from app.modules.identity.infrastructure.emis.certificates import to_certificates
from app.shared.contracts.emis import EmisAuthFailed, EmisCertificate, EmisUnavailable
from tests.certificates.conftest import (
    CertificatesHarness,
    level_field,
    number_field,
    text_field,
)

import pytest

CEFR = EmisCertificate(
    "cefr", "B2", 72, None, "English", dt.date(2025, 3, 15), dt.date(2027, 3, 14),
    "C-1", "https://cert.uzbmb.uz/c1.pdf",
)  # fmt: skip
NATIONAL = EmisCertificate(
    "national", "A+", 88.2, 91.5, "Fizika", dt.date(2025, 6, 1), None,
    "N-7", "https://api.uzbmb.uz/n7.pdf",
)  # fmt: skip


async def _with_builtin_types(h: CertificatesHarness) -> None:
    """The seeded CEFR and national types, with the fields the migration gives them."""
    await h.add_type(
        "cefr",
        builtin=True,
        custom_fields=[
            level_field(("A1", "A2", "B1", "B2", "C1", "C2")),
            number_field("score"),
            text_field("subject"),
            number_field("year", 1990, 2100),
            text_field("serial"),
        ],
    )
    await h.add_type(
        "national",
        builtin=True,
        custom_fields=[
            level_field(("A+", "A", "B+", "B", "C+", "C")),
            number_field("score"),
            number_field("percent", 0, 100),
            text_field("subject"),
            number_field("year", 1990, 2100),
            text_field("serial"),
        ],
    )


async def test_new_certificates_become_emis_entries_with_their_pdf(
    h: CertificatesHarness,
) -> None:
    """Two entries are created, each with one PDF in the student's files."""
    await _with_builtin_types(h)
    h.emis.items = [CEFR, NATIONAL]

    result = await h.services.import_emis.execute(h.ann.id)

    assert (result.created, result.updated, result.files, result.skipped) == (
        2,
        0,
        2,
        0,
    )
    entries = {
        e.custom_values["serial"]: e
        for e in await h.services.list_my_entries.execute(h.ann.id)
    }
    cefr = entries["C-1"]
    assert cefr.source.value == "emis"
    assert cefr.custom_values == {
        "level": "B2",
        "score": 72,
        "subject": "English",
        "year": 2025,
        "serial": "C-1",
    }
    assert (cefr.issued_at, cefr.expires_at) == (
        dt.date(2025, 3, 15),
        dt.date(2027, 3, 14),
    )
    assert entries["N-7"].custom_values["percent"] == 91.5
    assert [f.name for f in cefr.files] == ["cefr-C-1.pdf"]
    assert {f.owner_id for f in h.files.files.values()} == {h.ann.id}


async def test_importing_twice_does_not_duplicate_or_refetch(
    h: CertificatesHarness,
) -> None:
    """The second run finds both entries unchanged and downloads nothing."""
    await _with_builtin_types(h)
    h.emis.items = [CEFR, NATIONAL]
    await h.services.import_emis.execute(h.ann.id)
    h.fetcher.urls.clear()

    result = await h.services.import_emis.execute(h.ann.id)

    assert (result.created, result.updated, result.files, result.skipped) == (
        0,
        0,
        0,
        2,
    )
    assert len(await h.services.list_my_entries.execute(h.ann.id)) == 2
    assert h.fetcher.urls == []


async def test_a_changed_certificate_updates_the_same_entry(
    h: CertificatesHarness,
) -> None:
    """The (student, type, serial) key finds the entry; changed values are copied."""
    await _with_builtin_types(h)
    h.emis.items = [CEFR]
    await h.services.import_emis.execute(h.ann.id)
    h.emis.items = [
        EmisCertificate(
            "cefr", "C1", 85, None, "English", CEFR.issued_on, CEFR.expires_on,
            "C-1", CEFR.url,
        )  # fmt: skip
    ]

    result = await h.services.import_emis.execute(h.ann.id)

    [entry] = await h.services.list_my_entries.execute(h.ann.id)
    assert (result.created, result.updated) == (0, 1)
    assert (entry.custom_values["level"], entry.custom_values["score"]) == ("C1", 85)


async def test_the_same_serial_of_two_students_stays_separate(
    h: CertificatesHarness,
) -> None:
    """Dedupe is per student."""
    await _with_builtin_types(h)
    h.emis.items = [CEFR]

    await h.services.import_emis.execute(h.ann.id)
    await h.services.import_emis.execute(h.bob.id)

    assert len(await h.services.list_my_entries.execute(h.ann.id)) == 1
    assert len(await h.services.list_my_entries.execute(h.bob.id)) == 1


async def test_a_failed_download_keeps_the_entry_without_a_file(
    h: CertificatesHarness,
) -> None:
    """A PDF that cannot be fetched does not stop the import."""
    await _with_builtin_types(h)
    h.emis.items = [CEFR]
    h.fetcher.broken.add(CEFR.url or "")

    result = await h.services.import_emis.execute(h.ann.id)

    [entry] = await h.services.list_my_entries.execute(h.ann.id)
    assert (result.created, result.files, entry.files) == (1, 0, [])


async def test_items_without_a_serial_or_a_type_are_skipped(
    h: CertificatesHarness,
) -> None:
    """No serial means no stable key; a missing type means nowhere to put it."""
    await h.add_type("cefr", builtin=True)
    nameless = EmisCertificate("cefr", "B1", 60, None, None, None, None, None, None)
    h.emis.items = [nameless, NATIONAL]

    result = await h.services.import_emis.execute(h.ann.id)

    assert (result.created, result.skipped) == (0, 2)


async def test_an_emis_login_problem_is_not_a_401_for_the_student(
    h: CertificatesHarness,
) -> None:
    """EMIS refusing the stored login is reported as 'EMIS unavailable' (503)."""
    h.emis.error = EmisAuthFailed()

    with pytest.raises(EmisUnavailable):
        await h.services.import_emis.execute(h.ann.id)


def test_the_json_shapes_are_what_the_import_expects() -> None:
    """A raw profile result maps to the items the import consumes."""
    raw = {"dtm_certificate_info": {"cefr": [{"ser_num": "X", "level": "A2"}]}}

    assert to_certificates(raw)[0].serial == "X"
