"""EMIS ``dtm_certificate_info`` JSON becomes certificate contract objects."""

import datetime as dt
from typing import Any

from app.modules.identity.infrastructure.emis.certificates import to_certificates
from app.modules.identity.infrastructure.emis.fake import fake_certificate_block

PROFILE: dict[str, Any] = {
    "id": 1,
    "dtm_certificate_info": {
        "cefr": [
            {
                "level": "B2",
                "ball": 72,
                "subject": "English",
                "start_date": "2025-03-15",
                "end_date": "2027-03-14",
                "ser_num": "C-1",
                "hash": "https://cert.uzbmb.uz/c1.pdf",
            }
        ],
        "national": [
            {
                "level": "A+",
                "percent": "91,5",
                "ball": 88.2,
                "science_name": "Fizika",
                "start_at": "2025-06-01T00:00:00",
                "end_at": "2027-05-31",
                "cert_number": "N-7",
                "url": "https://api.uzbmb.uz/n7.pdf",
            }
        ],
    },
}


def test_cefr_item_maps_ball_to_score_and_hash_to_url() -> None:
    """cefr: level, ball, subject, start/end dates, ser_num, hash (PDF URL)."""
    cefr = to_certificates(PROFILE)[0]

    assert (cefr.kind, cefr.level, cefr.score, cefr.percent) == ("cefr", "B2", 72, None)
    assert (cefr.subject, cefr.serial, cefr.url) == (
        "English",
        "C-1",
        "https://cert.uzbmb.uz/c1.pdf",
    )
    assert (cefr.issued_on, cefr.expires_on) == (
        dt.date(2025, 3, 15),
        dt.date(2027, 3, 14),
    )


def test_national_item_maps_percent_science_name_and_cert_number() -> None:
    """national: level, percent, ball, science_name, start_at, end_at, cert_number."""
    national = to_certificates(PROFILE)[1]

    assert (national.kind, national.level, national.percent, national.score) == (
        "national",
        "A+",
        91.5,
        88.2,
    )
    assert (national.subject, national.serial, national.url) == (
        "Fizika",
        "N-7",
        "https://api.uzbmb.uz/n7.pdf",
    )
    assert national.issued_on == dt.date(2025, 6, 1)


def test_a_profile_without_certificates_gives_nothing() -> None:
    """Missing, null or odd blocks are tolerated."""
    assert to_certificates({}) == []
    assert to_certificates({"dtm_certificate_info": None}) == []
    assert (
        to_certificates({"dtm_certificate_info": {"cefr": "x", "national": [1]}}) == []
    )


def test_the_fake_emis_block_goes_through_the_same_mapping() -> None:
    """The sample data has one CEFR and one national certificate."""
    found = to_certificates(fake_certificate_block(78201))

    assert [c.kind for c in found] == ["cefr", "national"]
    assert all(c.serial and c.url for c in found)
