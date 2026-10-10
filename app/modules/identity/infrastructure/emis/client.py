"""HTTP client of the EMIS API (login, profile, curriculum, ratings, class hours)."""

import asyncio
import datetime as dt
from typing import Any, TypeVar

from app.modules.identity.application.register_models import (
    EmisAuthError,
    EmisRequestError,
)
from app.modules.identity.infrastructure.emis.mapping import (
    to_class_hours,
    to_classes,
    to_curriculum,
    to_profile,
    to_ratings,
    to_subjects,
)
from app.modules.identity.infrastructure.emis.models.responses.class_hours import (
    ClassHoursV1DTO,
)
from app.modules.identity.infrastructure.emis.models.responses.class_schedules import (
    ClassSchedulesV1DTO,
)
from app.modules.identity.infrastructure.emis.models.responses.curriculum import (
    CurriculumV1DTO,
)
from app.modules.identity.infrastructure.emis.models.responses.login import (
    LoginResultV1DTO,
)
from app.modules.identity.infrastructure.emis.models.responses.profile import (
    ProfileV1DTO,
)
from app.modules.identity.infrastructure.emis.models.responses.ratings import (
    RatingsV1DTO,
)
from app.settings import EmisSettings
from app.shared.contracts.emis import (
    EmisClass,
    EmisClassHour,
    EmisCurriculum,
    EmisProfile,
    EmisSubject,
    EmisSubjectRatings,
)

import httpx
from pydantic import BaseModel, ValidationError

CURRICULUM_PATH = "student-profiles/curriculum/"
CLASS_HOURS_PATH = "student-profiles/class-hours/"
CLASS_SCHEDULES_PATH = "student-profiles/class-schedules/"
EMIS_DATE = "%d.%m.%Y"
LOGIN_PATH = "student-profiles/login/"
_TIMEOUT = httpx.Timeout(20.0, connect=5.0)
M = TypeVar("M", bound=BaseModel)


def parse_result(model: type[M], result: dict[str, Any]) -> M:
    """Validate a ``result`` object; a wrong shape means EMIS changed."""
    try:
        return model.model_validate(result)
    except ValidationError as exc:
        raise EmisRequestError(f"unexpected {model.__name__} shape") from exc


class EmisClient:
    """Talks to EMIS; every call takes the access token, nothing is cached."""

    def __init__(
        self,
        http: httpx.AsyncClient,
        *,
        profile_path: str,
        concurrency: int = 20,
        request_delay_ms: int = 0,
    ) -> None:
        """Store the HTTP client and the concurrency limits."""
        self._http = http
        self._profile_path = profile_path.lstrip("/")
        self._semaphore = asyncio.Semaphore(concurrency)
        self._delay = request_delay_ms / 1000

    @classmethod
    def from_settings(cls, settings: EmisSettings) -> "EmisClient":
        """Build the client for ``EMIS__BASE_URL``."""
        http = httpx.AsyncClient(base_url=settings.base_url, timeout=_TIMEOUT)
        return cls(
            http,
            profile_path=settings.profile_path,
            concurrency=settings.concurrency,
            request_delay_ms=settings.request_delay_ms,
        )

    async def aclose(self) -> None:
        """Close the HTTP connection pool."""
        await self._http.aclose()

    async def _send(
        self,
        method: str,
        path: str,
        *,
        token: str | None = None,
        body: dict[str, str] | None = None,
    ) -> httpx.Response:
        """Send one request; any 401 is ``EmisAuthError``, other non-200 is an error."""
        headers = {"Authorization": token} if token else {}
        async with self._semaphore:
            if self._delay:
                await asyncio.sleep(self._delay)
            try:
                response = await self._http.request(
                    method, path, headers=headers, json=body
                )
            except httpx.HTTPError as exc:
                raise EmisRequestError(f"transport {type(exc).__name__}") from exc
        if response.status_code == 401:
            raise EmisAuthError()
        if response.status_code != 200:
            raise EmisRequestError(f"HTTP {response.status_code}")
        return response

    async def _request(
        self,
        method: str,
        path: str,
        *,
        token: str | None = None,
        body: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Send one request and return the ``result`` object of the response."""
        response = await self._send(method, path, token=token, body=body)
        return _result_of(response)

    async def get_json(self, path: str, token: str) -> Any:
        """GET a path and return the whole JSON body, not only ``result``."""
        response = await self._send("GET", path, token=token)
        try:
            return response.json()
        except ValueError as exc:
            raise EmisRequestError("response is not JSON") from exc

    async def login(self, login: str, password: str) -> str:
        """Log in and return the access token."""
        result = await self._request(
            "POST", LOGIN_PATH, body={"login": login, "password": password}
        )
        return parse_result(LoginResultV1DTO, result).access_token

    async def profile(self, token: str) -> EmisProfile:
        """Return the student's profile."""
        result = await self._request("GET", self._profile_path, token=token)
        return to_profile(parse_result(ProfileV1DTO, result))

    async def curriculum(self, token: str) -> list[EmisSubject]:
        """Return the subjects of the curriculum."""
        result = await self._request("GET", CURRICULUM_PATH, token=token)
        return to_subjects(parse_result(CurriculumV1DTO, result))

    async def curriculum_detail(self, token: str) -> EmisCurriculum:
        """Return the whole curriculum: semesters, hours per subject, exams."""
        result = await self._request("GET", CURRICULUM_PATH, token=token)
        return to_curriculum(parse_result(CurriculumV1DTO, result))

    async def ratings(
        self, token: str, subject_id: int, semester: int
    ) -> EmisSubjectRatings:
        """Return the marks and the semester rating of one subject."""
        path = (
            f"student-profiles/edu-subjects/{subject_id}/ratings/?semester={semester}"
        )
        result = await self._request("GET", path, token=token)
        dto = parse_result(RatingsV1DTO, result)
        return to_ratings(
            dto, raw_result=result, subject_id=subject_id, semester=semester
        )

    async def class_hours(self, token: str) -> list[EmisClassHour]:
        """Return the bells; this response has a ``results`` list, not ``result``."""
        body = await self.get_json(CLASS_HOURS_PATH, token)
        if not isinstance(body, dict) or not isinstance(body.get("results"), list):
            raise EmisRequestError("class hours response has no results list")
        return to_class_hours(parse_result(ClassHoursV1DTO, body))

    async def timetable(
        self, token: str, begin: dt.date, end: dt.date
    ) -> list[EmisClass]:
        """Return the classes on begin..end, one request per Monday-to-Sunday week.

        ``begin_date`` and ``end_date`` are ``DD.MM.YYYY``; the answer is a ``results``
        list with one item per day. EMIS is asked for one week at a time.
        """
        classes: list[EmisClass] = []
        for first, last in _weeks(begin, end):
            path = (
                f"{CLASS_SCHEDULES_PATH}?begin_date={first.strftime(EMIS_DATE)}"
                f"&end_date={last.strftime(EMIS_DATE)}"
            )
            body = await self.get_json(path, token)
            if not isinstance(body, dict) or not isinstance(body.get("results"), list):
                raise EmisRequestError("class schedules response has no results list")
            classes.extend(to_classes(parse_result(ClassSchedulesV1DTO, body)))
        return classes


def _weeks(begin: dt.date, end: dt.date) -> list[tuple[dt.date, dt.date]]:
    """Split begin..end at Mondays: [(begin, first Sunday), (Monday, Sunday), ...]."""
    spans: list[tuple[dt.date, dt.date]] = []
    first = begin
    while first <= end:
        sunday = first + dt.timedelta(days=7 - first.isoweekday())
        spans.append((first, min(sunday, end)))
        first = sunday + dt.timedelta(days=1)
    return spans


def _result_of(response: httpx.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError as exc:
        raise EmisRequestError("response is not JSON") from exc
    result = payload.get("result") if isinstance(payload, dict) else None
    if not isinstance(result, dict):
        raise EmisRequestError("response has no result object")
    return result
