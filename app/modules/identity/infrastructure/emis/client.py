"""HTTP client of the EMIS API (login, profile, curriculum, ratings)."""

import asyncio
from typing import Any, TypeVar

from app.modules.identity.application.register_models import (
    EmisAuthError,
    EmisRequestError,
)
from app.modules.identity.infrastructure.emis.mapping import (
    to_profile,
    to_ratings,
    to_subjects,
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
from app.shared.contracts.emis import EmisProfile, EmisSubject, EmisSubjectRatings

import httpx
from pydantic import BaseModel, ValidationError

CURRICULUM_PATH = "student-profiles/curriculum/"
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

    async def _request(
        self,
        method: str,
        path: str,
        *,
        token: str | None = None,
        body: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Send one request and return the ``result`` object of the response."""
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
        return _result_of(response)

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


def _result_of(response: httpx.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError as exc:
        raise EmisRequestError("response is not JSON") from exc
    result = payload.get("result") if isinstance(payload, dict) else None
    if not isinstance(result, dict):
        raise EmisRequestError("response has no result object")
    return result
