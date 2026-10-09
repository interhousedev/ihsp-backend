"""EmisSource over the identity process's internal API (worker, api and bot use it)."""

import datetime as dt
from datetime import date, time
from typing import Any
from uuid import UUID

from app.settings import Settings
from app.shared.contracts.emis import (
    EmisAuthFailed,
    EmisClass,
    EmisClassHour,
    EmisMark,
    EmisMarkType,
    EmisProfile,
    EmisSubject,
    EmisSubjectRatings,
    EmisTeacher,
    EmisTopic,
    EmisUnavailable,
)

import httpx

_TIMEOUT = httpx.Timeout(60.0, connect=5.0)  # the gateway may log in to EMIS first
_AUTH_FAILED_TYPE = EmisAuthFailed.code


class HttpEmisSource:
    """Calls ``/internal/emis/*`` with the service token; it never sees Vault."""

    def __init__(
        self,
        *,
        gateway_url: str,
        service_token: str,
        http: httpx.AsyncClient | None = None,
    ) -> None:
        """Store the gateway URL (``EMIS__GATEWAY_URL``) and the service token."""
        self._base = gateway_url.rstrip("/")
        self._headers = {"Authorization": f"Bearer {service_token}"}
        self._http = http or httpx.AsyncClient(timeout=_TIMEOUT)

    @classmethod
    def from_settings(cls, settings: Settings) -> "HttpEmisSource":
        """Build the source from ``EMIS__GATEWAY_URL`` and ``TOKENS__SERVICE_TOKEN``."""
        return cls(
            gateway_url=settings.emis.gateway_url,
            service_token=settings.tokens.service_token.get_secret_value(),
        )

    async def aclose(self) -> None:
        """Close the HTTP connection pool."""
        await self._http.aclose()

    async def profile(self, user_id: UUID) -> EmisProfile:
        """Return the student's EMIS profile."""
        body = await self._get(f"{user_id}/profile")
        return EmisProfile(
            emis_student_id=body["emis_student_id"],
            first_name=body["first_name"],
            last_name=body["last_name"],
            middle_name=body["middle_name"],
            institution_id=body["institution_id"],
            group_emis_id=body["group_emis_id"],
            group_name=body["group_name"],
            current_semester=body["current_semester"],
            curriculum_id=body["curriculum_id"],
        )

    async def subjects(self, user_id: UUID) -> list[EmisSubject]:
        """Return the student's subjects."""
        body = await self._get(f"{user_id}/subjects")
        return [
            EmisSubject(
                emis_subject_id=item["emis_subject_id"],
                name_uz=item["name_uz"],
                name_ru=item["name_ru"],
                name_en=item["name_en"],
            )
            for item in body
        ]

    async def ratings(
        self, user_id: UUID, emis_subject_id: int, semester: int
    ) -> EmisSubjectRatings:
        """Return the marks and the semester rating of one subject."""
        body = await self._get(
            f"{user_id}/ratings", {"subject": emis_subject_id, "semester": semester}
        )
        return EmisSubjectRatings(
            emis_subject_id=body["emis_subject_id"],
            semester=body["semester"],
            semester_rating=body["semester_rating"],
            marks=tuple(
                EmisMark(
                    type=EmisMarkType(mark["type"]),
                    date=date.fromisoformat(mark["date"]),
                    value=mark["value"],
                )
                for mark in body["marks"]
            ),
            payload_hash=body["payload_hash"],
        )

    async def class_hours(self, user_id: UUID) -> list[EmisClassHour]:
        """Return the bells of the lyceum."""
        body = await self._get(f"{user_id}/class-hours")
        return [
            EmisClassHour(
                pair_number=item["pair_number"],
                begin_time=time.fromisoformat(item["begin_time"]),
                end_time=time.fromisoformat(item["end_time"]),
            )
            for item in body
        ]

    async def timetable(
        self, user_id: UUID, begin: dt.date, end: dt.date
    ) -> list[EmisClass]:
        """Return the student's classes on the dates begin..end."""
        body = await self._get(
            f"{user_id}/timetable",
            {"begin": begin.isoformat(), "end": end.isoformat()},
        )
        return [_emis_class(item) for item in body]

    async def _get(self, path: str, params: dict[str, int | str] | None = None) -> Any:
        try:
            response = await self._http.get(
                f"{self._base}/{path}", params=params, headers=self._headers
            )
        except httpx.HTTPError as exc:
            raise EmisUnavailable(
                support_details=f"gateway unreachable: {type(exc).__name__}"
            ) from exc
        if response.status_code == 200:
            return response.json()
        raise _error_for(response)


def _emis_class(item: dict[str, Any]) -> EmisClass:
    subject, teacher, topic = item["subject"], item["teacher"], item["topic"]
    return EmisClass(
        class_id=item["class_id"],
        date=date.fromisoformat(item["date"]),
        pair_number=item["pair_number"],
        subject=EmisSubject(
            emis_subject_id=subject["emis_subject_id"],
            name_uz=subject["name_uz"],
            name_ru=subject["name_ru"],
            name_en=subject["name_en"],
        ),
        teacher=(
            EmisTeacher(
                emis_id=teacher["emis_id"],
                first_name=teacher["first_name"],
                last_name=teacher["last_name"],
                middle_name=teacher["middle_name"],
            )
            if teacher
            else None
        ),
        room=item["room"],
        subgroup=item["subgroup"],
        kind=item["kind"],
        topic=(
            EmisTopic(
                name=topic["name"],
                description=topic["description"],
                topic_file_url=topic["topic_file_url"],
                homework_file_url=topic["homework_file_url"],
                video_url=topic["video_url"],
            )
            if topic
            else None
        ),
    )


def _error_for(response: httpx.Response) -> EmisAuthFailed | EmisUnavailable:
    """401 with ``emis/auth-failed`` is the student's problem, all else is ours."""
    try:
        problem = response.json()
        problem_type = problem.get("type") if isinstance(problem, dict) else None
    except ValueError:
        problem_type = None
    if response.status_code == 401 and problem_type == _AUTH_FAILED_TYPE:
        return EmisAuthFailed(support_details="EMIS rejected the credentials")
    return EmisUnavailable(
        support_details=f"gateway answered {response.status_code} {problem_type}"
    )
