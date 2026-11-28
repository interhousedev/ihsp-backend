"""The overall student rating of the current academic year (all students)."""

from dataclasses import asdict
from typing import Any
from uuid import UUID

from app.modules.academic.application.marks.ports.rating import RatingSource
from app.modules.academic.application.marks.view_context import caller_locale
from app.modules.academic.domain.marks.overall_rating import (
    Breakdown,
    RatedCertificate,
    RatingInput,
    RatingWeights,
    rank,
)
from app.shared.actor import Actor
from app.shared.clock import Clock, local_today
from app.shared.contracts.certificates import CertificateRoster
from app.shared.contracts.identity import (
    IdentityDirectory,
    UserRef,
    UserStatus,
    peer_photo_ids,
)

PHOTO_URL_TTL_SECONDS = 600
MAX_LIMIT = 100


class GetOverallRating:
    """Rank every active student of a visible group by the overall score.

    The caller gets the top ``limit`` rows, their own place and breakdown, and the
    weights the page explains. Photos follow ``peer_photo_ids``.
    """

    def __init__(
        self,
        *,
        source: RatingSource,
        certificates: CertificateRoster,
        identity: IdentityDirectory,
        clock: Clock,
        weights: RatingWeights,
    ) -> None:
        """Store collaborators."""
        self._source = source
        self._certificates = certificates
        self._identity = identity
        self._clock = clock
        self._weights = weights

    async def execute(self, actor: Actor, limit: int) -> dict[str, Any]:
        """Return the year, the weights, the top rows and the caller's own row."""
        limit = max(1, min(limit, MAX_LIMIT))
        result: dict[str, Any] = {
            "academic_year": None,
            "weights": _weights(self._weights),
            "total": 0,
            "top": [],
            "me": None,
        }
        year = await self._source.academic_year(local_today(self._clock))
        if year is None:
            return result
        result["academic_year"] = {
            "label": year.label,
            "starts_on": year.starts_on,
            "ends_on": year.ends_on,
        }
        facts = await self._source.year_facts(year.starts_on, year.ends_on)
        users = await self._identity.get_users(
            sorted((f.student_id for f in facts), key=str)
        )
        facts = [
            f
            for f in facts
            if f.student_id in users and users[f.student_id].status is UserStatus.ACTIVE
        ]
        locale = await caller_locale(self._identity, actor.user_id)
        certs = await self._certificates.for_students([f.student_id for f in facts])
        inputs = [
            RatingInput(
                student_id=f.student_id,
                group_name=f.group_name,
                mark_sum=f.mark_sum,
                mark_count=f.mark_count,
                platform_absences=f.platform_absences,
                emis_absences=f.emis_absences,
                work_offs=f.work_offs,
                certificates=[
                    RatedCertificate(
                        name=c.name(locale),
                        category=c.category,
                        level=_text(c.values.get("level")),
                        issued_at=c.issued_at,
                    )
                    for c in certs.get(f.student_id, [])
                    if c.issued_at is not None
                    and year.starts_on <= c.issued_at <= year.ends_on
                ],
            )
            for f in facts
        ]
        ranked = rank(inputs, self._weights)
        top = ranked[:limit]
        mine = next((pb for pb in ranked if pb[1].student_id == actor.user_id), None)
        shown = {b.student_id: users[b.student_id] for _, b in top}
        if mine is not None:
            shown[actor.user_id] = users[actor.user_id]
        photos = await self._identity.photo_urls(
            peer_photo_ids(actor.user_id, shown, actor.roles),
            ttl_seconds=PHOTO_URL_TTL_SECONDS,
        )
        result["total"] = len(ranked)
        result["top"] = [
            _row(place, b, users[b.student_id], photos, actor.user_id)
            for place, b in top
        ]
        if mine is not None:
            place, own = mine
            row = _row(place, own, users[actor.user_id], photos, actor.user_id)
            row["breakdown"] = _breakdown(own)
            result["me"] = row
        return result


def _text(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _row(
    place: int, b: Breakdown, user: UserRef, photos: dict[UUID, str], me: UUID
) -> dict[str, Any]:
    return {
        "place": place,
        "student_id": b.student_id,
        "full_name": f"{user.first_name} {user.last_name}".strip(),
        "group_name": b.group_name,
        "score": b.score,
        "photo_url": photos.get(b.student_id),
        "is_me": b.student_id == me,
    }


def _breakdown(b: Breakdown) -> dict[str, Any]:
    return {
        "base": b.base,
        "certificates": [asdict(c) for c in b.certificates],
        "certificate_points": b.certificate_points,
        "mark_average": b.mark_average,
        "mark_count": b.mark_count,
        "marks_points": b.marks_points,
        "absences": b.absences,
        "absence_points": b.absence_points,
        "work_offs": b.work_offs,
        "work_off_points": b.work_off_points,
    }


def _weights(w: RatingWeights) -> dict[str, Any]:
    return {
        "base": w.base,
        "category_points": dict(w.category_points),
        "level_points": dict(w.level_points),
        "marks_threshold": w.marks_threshold,
        "marks_points": w.marks_points,
        "absence_points": w.absence_points,
        "work_off_points": w.work_off_points,
    }
