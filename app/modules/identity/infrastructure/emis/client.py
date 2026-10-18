"""HTTP client of the EMIS API (login, profile, curriculum, ratings, class hours)."""

import asyncio
import datetime as dt
import re
from typing import Any, TypeVar
from urllib.parse import SplitResult, unquote, urlsplit

from app.modules.identity.application.register_models import (
    EmisAuthError,
    EmisFileRetryError,
    EmisPausedError,
    EmisRequestError,
)
from app.modules.identity.infrastructure.emis.certificates import to_certificates
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
from app.modules.identity.infrastructure.emis.rate_limit import EmisRateLimiter
from app.settings import EmisSettings
from app.shared.contracts.emis import (
    EmisCertificate,
    EmisClass,
    EmisClassHour,
    EmisCurriculum,
    EmisFile,
    EmisProfile,
    EmisSubject,
    EmisSubjectRatings,
)
from app.shared.emis_pause import EmisPause

import httpx
import structlog
from pydantic import BaseModel, ValidationError
from redis.asyncio import Redis

CURRICULUM_PATH = "student-profiles/curriculum/"
CLASS_HOURS_PATH = "student-profiles/class-hours/"
CLASS_SCHEDULES_PATH = "student-profiles/class-schedules/"
EMIS_DATE = "%d.%m.%Y"
LOGIN_PATH = "student-profiles/login/"
_TIMEOUT = httpx.Timeout(20.0, connect=5.0)
_DOWNLOAD_TIMEOUT = httpx.Timeout(60.0, connect=5.0)
_DOWNLOAD_ATTEMPTS = 3
_DOWNLOAD_BACKOFF_SECONDS = 0.5
_TRANSIENT_MARKERS = ("http_502", "http_503", "http_504", "transport")
DEFAULT_PAUSE_SECONDS = 60.0  # a 429 without Retry-After
MAX_PAUSE_SECONDS = 3600.0
log = structlog.get_logger(__name__)
_FILENAME = re.compile(r"filename\*?=(?:UTF-8'')?\"?([^\";]+)", re.IGNORECASE)
M = TypeVar("M", bound=BaseModel)


def parse_result(model: type[M], result: dict[str, Any]) -> M:
    """Validate a ``result`` object; a wrong shape means EMIS changed."""
    try:
        return model.model_validate(result)
    except ValidationError as exc:
        raise EmisRequestError(f"unexpected {model.__name__} shape") from exc


def _status_reason(status: int) -> str:
    """Upstream reason: rate_limit for 429, else http_<status>."""
    return "rate_limit" if status == 429 else f"http_{status}"


def _is_transient(exc: EmisRequestError) -> bool:
    """A CDN 5xx or transport failure may succeed later."""
    return str(exc).startswith(_TRANSIENT_MARKERS)


def _retry_after(response: httpx.Response) -> float | None:
    """The Retry-After header in seconds (numeric form only), clamped."""
    raw = response.headers.get("retry-after", "").strip()
    if not raw.isdigit():
        return None
    return min(max(float(raw), 1.0), MAX_PAUSE_SECONDS)


class EmisClient:
    """Talks to EMIS; every call takes the access token, nothing is cached."""

    def __init__(
        self,
        http: httpx.AsyncClient,
        *,
        profile_path: str,
        limiter: EmisRateLimiter,
        pause: EmisPause,
        max_qps: int,
        file_max_qps: int,
        concurrency: int = 20,
        request_delay_ms: int = 0,
    ) -> None:
        """Store the HTTP client, the shared limits and the shared pause."""
        self._http = http
        self._profile_path = profile_path.lstrip("/")
        self._limiter = limiter
        self._pause = pause
        self._max_qps = max_qps
        self._file_max_qps = file_max_qps
        self._semaphore = asyncio.Semaphore(concurrency)
        self._delay = request_delay_ms / 1000

    @classmethod
    def from_settings(cls, settings: EmisSettings, redis: Redis) -> "EmisClient":
        """Build the client for ``EMIS__BASE_URL``; the limits are shared via Redis."""
        http = httpx.AsyncClient(base_url=settings.base_url, timeout=_TIMEOUT)
        return cls(
            http,
            profile_path=settings.profile_path,
            limiter=EmisRateLimiter(redis),
            pause=EmisPause(redis),
            max_qps=settings.max_qps,
            file_max_qps=settings.file_max_qps,
            concurrency=settings.concurrency,
            request_delay_ms=settings.request_delay_ms,
        )

    async def aclose(self) -> None:
        """Close the HTTP connection pool."""
        await self._http.aclose()

    async def _gate(self, bucket: str, qps: int) -> None:
        """Refuse while EMIS asked for a pause; else wait for the shared allowance."""
        wait_for = await self._pause.remaining()
        if wait_for > 0:
            raise EmisPausedError(wait_for)
        await self._limiter.acquire(bucket, qps)

    async def _pause_if_asked(self, response: httpx.Response) -> None:
        """A 429, or a 5xx with Retry-After, means EMIS wants rest: pause all."""
        retry_after = _retry_after(response)
        if response.status_code != 429 and retry_after is None:
            return
        seconds = retry_after if retry_after is not None else DEFAULT_PAUSE_SECONDS
        await self._pause.pause(seconds)
        log.warning("emis_paused", status=response.status_code, seconds=seconds)
        raise EmisPausedError(seconds)

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
            await self._gate("api", self._max_qps)
            try:
                response = await self._http.request(
                    method, path, headers=headers, json=body
                )
            except httpx.HTTPError as exc:
                raise EmisRequestError(f"transport {type(exc).__name__}") from exc
        if response.status_code == 401:
            raise EmisAuthError()
        if response.status_code != 200:
            await self._pause_if_asked(response)
            raise EmisRequestError(_status_reason(response.status_code))
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

    async def certificates(self, token: str) -> list[EmisCertificate]:
        """Return the CEFR and national certificates of the profile."""
        result = await self._request("GET", self._profile_path, token=token)
        return to_certificates(result)

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

    async def download(self, token: str, url: str, max_bytes: int) -> EmisFile:
        """Stream a material URL, stopping past ``max_bytes``.

        The EMIS token goes only to the EMIS host itself, never to another server
        (files often sit on a CDN that needs no session).
        """
        parts = urlsplit(url)
        if parts.scheme not in {"http", "https"} or not parts.hostname:
            raise EmisRequestError("material URL is not http(s)")
        own_host = parts.hostname == self._http.base_url.host
        headers = {"Authorization": token} if own_host else {}
        for attempt in range(1, _DOWNLOAD_ATTEMPTS + 1):
            try:
                return await self._download_once(
                    url, headers, own_host, max_bytes, parts
                )
            except EmisPausedError:
                raise  # EMIS asked for a rest: no retry now, the sync stops
            except EmisRequestError as exc:
                transient = _is_transient(exc)
                log.warning(
                    "emis_download_failed",
                    host=parts.hostname,
                    attempt=attempt,
                    reason=str(exc),
                    transient=transient,
                )
                if not transient:
                    raise
                if attempt == _DOWNLOAD_ATTEMPTS:
                    # a 5xx or a transport failure: the file stays pending for next sync
                    raise EmisFileRetryError(str(exc)) from exc
                await asyncio.sleep(_DOWNLOAD_BACKOFF_SECONDS * attempt)
        raise AssertionError("unreachable")  # the loop returns or raises

    async def _download_once(
        self,
        url: str,
        headers: dict[str, str],
        own_host: bool,
        max_bytes: int,
        parts: SplitResult,
    ) -> EmisFile:
        async with self._semaphore:
            await self._gate("file", self._file_max_qps)
            try:
                async with self._http.stream(
                    "GET",
                    url,
                    headers=headers,
                    timeout=_DOWNLOAD_TIMEOUT,
                    follow_redirects=True,
                ) as response:
                    if response.status_code == 401 and own_host:
                        raise EmisAuthError()
                    if response.status_code != 200:
                        await self._pause_if_asked(response)
                        raise EmisRequestError(_status_reason(response.status_code))
                    data = await _read_limited(response, max_bytes)
            except httpx.HTTPError as exc:
                raise EmisRequestError(f"transport {type(exc).__name__}") from exc
        return EmisFile(
            name=_file_name(response, parts.path),
            content_type=response.headers.get("content-type"),
            data=data,
        )


async def _read_limited(response: httpx.Response, max_bytes: int) -> bytes:
    declared = response.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > max_bytes:
        raise EmisRequestError("file too large")
    chunks: list[bytes] = []
    size = 0
    async for chunk in response.aiter_bytes():
        size += len(chunk)
        if size > max_bytes:
            raise EmisRequestError("file too large")
        chunks.append(chunk)
    return b"".join(chunks)


def _file_name(response: httpx.Response, path: str) -> str:
    """The Content-Disposition name, else the last segment of the URL path."""
    found = _FILENAME.search(response.headers.get("content-disposition", ""))
    raw = found.group(1) if found else path.rstrip("/").rsplit("/", 1)[-1]
    return unquote(raw).strip() or "file"


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
