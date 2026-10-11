"""EmisSource over the identity process's internal API (worker, api and bot use it)."""

import asyncio
import datetime as dt
import random
from collections.abc import Awaitable, Callable
from datetime import date, time
from typing import Any
from uuid import UUID

from app.settings import Settings
from app.shared.contracts.emis import (
    EmisAuthFailed,
    EmisClass,
    EmisClassHour,
    EmisCredentialsMissing,
    EmisCurriculum,
    EmisCurriculumItem,
    EmisCurriculumSubject,
    EmisDirection,
    EmisMark,
    EmisMarkType,
    EmisName,
    EmisProfile,
    EmisSemesterDates,
    EmisSemesterSubject,
    EmisSubject,
    EmisSubjectRatings,
    EmisTeacher,
    EmisTopic,
    EmisUnavailable,
    EmisYear,
)

import httpx
import structlog

log = structlog.get_logger(__name__)

_TIMEOUT = httpx.Timeout(60.0, connect=5.0)  # the gateway may log in to EMIS first
# Every call here is an idempotent GET: one transport blip (a connect or read
# timeout, a dropped connection, a 502/503/504 from the edge) gets one more try
# after a short jittered pause instead of failing the whole sync step.
RETRY_STATUSES = frozenset({502, 503, 504})
RETRY_DELAY_SECONDS = 0.5
RETRY_JITTER_SECONDS = 0.5
_TRANSIENT = (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError)
_AUTH_FAILED_TYPE = EmisAuthFailed.code
_CREDENTIALS_MISSING_TYPE = EmisCredentialsMissing.code


class HttpEmisSource:
    """Calls ``/internal/emis/*`` with the service token; it never sees Vault."""

    def __init__(
        self,
        *,
        gateway_url: str,
        service_token: str,
        http: httpx.AsyncClient | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        """Store the gateway URL (``EMIS__GATEWAY_URL``) and the service token."""
        self._base = gateway_url.rstrip("/")
        self._headers = {"Authorization": f"Bearer {service_token}"}
        self._http = http or httpx.AsyncClient(timeout=_TIMEOUT)
        self._sleep = sleep

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

    async def curriculum(self, user_id: UUID) -> EmisCurriculum:
        """Return the whole curriculum of the student: semesters, hours, exams."""
        return _emis_curriculum(await self._get(f"{user_id}/curriculum"))

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
        response = await self._get_once(path, params)
        if response is None or _is_edge_failure(response):
            log.warning(
                "emis_gateway_retry",
                path=path,
                status=None if response is None else response.status_code,
            )
            jitter = random.random() * RETRY_JITTER_SECONDS
            await self._sleep(RETRY_DELAY_SECONDS + jitter)
            retried = await self._get_once(path, params)
            if retried is None:
                raise EmisUnavailable(support_details="gateway unreachable twice")
            response = retried
        if response.status_code == 200:
            return response.json()
        raise _error_for(response)

    async def _get_once(
        self, path: str, params: dict[str, int | str] | None
    ) -> httpx.Response | None:
        """One request; None stands for a transport failure worth one retry."""
        try:
            return await self._http.get(
                f"{self._base}/{path}", params=params, headers=self._headers
            )
        except _TRANSIENT as exc:
            log.warning(
                "emis_gateway_transport_error", path=path, error=type(exc).__name__
            )
            return None
        except httpx.HTTPError as exc:
            raise EmisUnavailable(
                support_details=f"gateway unreachable: {type(exc).__name__}"
            ) from exc


def _optional_date(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


def _name(body: dict[str, str]) -> EmisName:
    return EmisName(uz=body["uz"], ru=body["ru"], en=body["en"])


def _year(body: dict[str, Any] | None) -> EmisYear | None:
    if body is None:
        return None
    return EmisYear(
        code=body["code"],
        name=body["name"],
        from_date=_optional_date(body["from_date"]),
        to_date=_optional_date(body["to_date"]),
    )


def _semester_subject(item: dict[str, Any]) -> EmisSemesterSubject:
    return EmisSemesterSubject(
        semester_number=item["semester_number"],
        emis_subject_id=item["emis_subject_id"],
        name=_name(item["name"]),
        subject_type_id=item["subject_type_id"],
        study_hours=item["study_hours"],
        class_hours=item["class_hours"],
        independent_hours=item["independent_hours"],
        is_separated=item["is_separated"],
    )


def _curriculum_items(items: list[dict[str, Any]]) -> tuple[EmisCurriculumItem, ...]:
    return tuple(
        EmisCurriculumItem(item["emis_id"], _name(item["name"]), item["study_hours"])
        for item in items
    )


def _emis_curriculum(body: dict[str, Any]) -> EmisCurriculum:
    direction, speciality = body["direction"], body["speciality"]
    return EmisCurriculum(
        emis_id=body["emis_id"],
        name=body["name"],
        direction=(
            EmisDirection(direction["emis_id"], direction["name"], direction["code"])
            if direction
            else None
        ),
        speciality=_name(speciality) if speciality else None,
        edu_form=body["edu_form"],
        language_code=body["language_code"],
        rating_min=body["rating_min"],
        rating_max=body["rating_max"],
        start_year=_year(body["start_year"]),
        end_year=_year(body["end_year"]),
        semesters_count=body["semesters_count"],
        status=body["status"],
        semesters=tuple(
            EmisSemesterDates(
                number=item["number"],
                starts_on=date.fromisoformat(item["starts_on"]),
                ends_on=date.fromisoformat(item["ends_on"]),
            )
            for item in body["semesters"]
        ),
        subjects=tuple(
            EmisCurriculumSubject(
                emis_subject_id=item["emis_subject_id"],
                name=_name(item["name"]),
                subject_type_id=item["subject_type_id"],
                study_hours=item["study_hours"],
            )
            for item in body["subjects"]
        ),
        semester_subjects=tuple(
            _semester_subject(i) for i in body["semester_subjects"]
        ),
        exams=_curriculum_items(body["exams"]),
        vocational_subjects=_curriculum_items(body["vocational_subjects"]),
    )


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


def _is_edge_failure(response: httpx.Response) -> bool:
    """A 502/503/504 without a problem body comes from the edge, not the gateway.

    The gateway's own 503s (`emis/unavailable`, `emis/credentials-missing`) carry a
    problem `type` and are final: retrying them only delays the student's answer.
    """
    return response.status_code in RETRY_STATUSES and _problem_type(response) is None


def _problem_type(response: httpx.Response) -> str | None:
    try:
        problem = response.json()
    except ValueError:
        return None
    return problem.get("type") if isinstance(problem, dict) else None


def _error_for(response: httpx.Response) -> EmisAuthFailed | EmisUnavailable:
    """401 with ``emis/auth-failed`` is the student's problem, all else is ours.

    ``emis/credentials-missing`` is a student without a stored login: not an outage.
    """
    problem_type = _problem_type(response)
    if response.status_code == 401 and problem_type == _AUTH_FAILED_TYPE:
        return EmisAuthFailed(support_details="EMIS rejected the credentials")
    if problem_type == _CREDENTIALS_MISSING_TYPE:
        return EmisCredentialsMissing(support_details="no stored EMIS login")
    return EmisUnavailable(
        support_details=f"gateway answered {response.status_code} {problem_type}"
    )
