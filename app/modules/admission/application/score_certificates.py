"""Standard-exam certificates of the platform shown among the test scores.

A certificate entry of a type flagged ``standard`` whose code matches a test of the
catalog (`sat` -> `sat`, `ielts` -> `ielts_academic`) becomes a read-only received
entry of that test, so its scores need no re-entry. Entries the student also typed in
by hand are not duplicated. Other standard certificates are listed on their own.
"""

import datetime as dt
from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any
from uuid import UUID

from app.modules.admission.domain.errors import ScoreInvalidError
from app.modules.admission.domain.test_scores import Score, ScoreEntry, ScoreTest
from app.shared.contracts.certificates import StudentCertificate


@dataclass(frozen=True, slots=True)
class ExamCertificate:
    """A standard certificate without a matching test of the catalog."""

    entry_id: UUID
    names: dict[str, str]
    type_code: str
    issued_at: dt.date | None
    expires_at: dt.date | None
    values: dict[str, Any] = field(default_factory=dict)


def match_test(tests: Sequence[ScoreTest], code: str) -> ScoreTest | None:
    """The test whose key is the type code or starts with `<code>_`."""
    exact = next((t for t in tests if t.key == code), None)
    return exact or next((t for t in tests if t.key.startswith(f"{code}_")), None)


def _scores(
    test: ScoreTest, values: dict[str, Any]
) -> tuple[dict[str, Score], Score | None]:
    """The values that fit the test's ranges; the rest is left out."""
    sections: dict[str, Score] = {}
    for part in test.sections:
        if values.get(part.key) is not None:
            try:
                sections[part.key] = part.check(values[part.key])
            except ScoreInvalidError:
                continue
    total: Score | None = None
    if test.total is not None and values.get("score") is not None:
        try:
            total = test.total.check(values["score"])
        except ScoreInvalidError:
            total = None
    return sections, total


def _same(a: ScoreEntry, b: ScoreEntry) -> bool:
    """Whether a typed-in entry already records this certificate."""
    if a.status != "score_received":
        return False
    if a.test_date and b.test_date and a.test_date != b.test_date:
        return False
    if a.total is not None and a.total == b.total:
        return True
    return b.total is None and b.level is not None and a.level == b.level


def merge_certificates(
    student_id: UUID,
    entries: list[ScoreEntry],
    tests: Sequence[ScoreTest],
    certs: Sequence[StudentCertificate],
    now: dt.datetime,
) -> tuple[list[ScoreEntry], list[ExamCertificate]]:
    """Return the entries with the certificate ones added, and the unmatched exams."""
    merged = list(entries)
    unmatched: list[ExamCertificate] = []
    for cert in certs:
        if not cert.standard:
            continue
        test = match_test(tests, cert.type_code)
        if test is None:
            unmatched.append(
                ExamCertificate(
                    cert.entry_id,
                    cert.names,
                    cert.type_code,
                    cert.issued_at,
                    cert.expires_at,
                    cert.values,
                )
            )
            continue
        sections, total = _scores(test, cert.values)
        level = str(cert.values["level"]) if cert.values.get("level") else None
        virtual = ScoreEntry(
            id=cert.entry_id,
            student_id=student_id,
            test_id=test.id,
            status="score_received",
            test_date=cert.issued_at,
            registration_deadline=None,
            label=None,
            level=level,
            sections=sections,
            total=total if isinstance(total, Decimal | str) else None,
            certificate_document_id=None,
            verification_url=None,
            send_note=None,
            is_official=True,
            verified_by=None,
            verified_at=None,
            created_at=now,
            updated_at=now,
            source="certificate",
        )
        if not any(_same(e, virtual) for e in entries if e.test_id == test.id):
            merged.append(virtual)
    return merged, unmatched
