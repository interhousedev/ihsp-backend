"""End-to-end smoke test of a running IHSP backend (dev mode or local full stack).

Usage (the stack must be up, demo data seeded, Hydra clients registered):

    uv run python scripts/smoke.py [--api URL] [--hydra URL] [--mailpit URL]
                                   [--redis URL] [--emis LOGIN ...]

Everything goes through public HTTP: scripted OAuth PKCE login through Hydra plus
`/v1/id/login` for each role, then the flows of README.md (registration, today,
timetable, homework, attendance, materials, files, short links, rooms, assistant,
flash cards, LMS, broadcast, MCP, iCal, administration). Each step prints PASS or
FAIL (with the response on failure); the exit code is 1 when a step failed.

Needs fake EMIS and OpenRouter (``EMIS__MODE=fake``, ``OPENROUTER__MODE=fake``) and the
fake Telegram sender (``TELEGRAM__MODE=fake``), whose outbox is the Redis list
``fake-telegram:outbox``. Re-running is safe: created objects get a run suffix and
one-off state (registration, Telegram link) is reused.
"""

import argparse
import asyncio
import base64
import hashlib
import hmac
import json
import re
import secrets
import socket
import sys
import time
import traceback
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse
from uuid import UUID

import httpx
import redis.asyncio as aioredis

OUTBOX_KEY = "fake-telegram:outbox"
NEXT_STUDENT_KEY = "smoke:emis-next"
LAST_STUDENT_KEY = "smoke:last-student"
SCOPE = "openid offline_access"
AUDIENCE = "ihsp-api"
APP_PORTS = {"id": 3001, "sp": 3002, "staff": 3003, "admin": 3004, "lms": 3005}
DEV_BOT_TOKEN = "000:dev"
ADMIN = ("admin.ihsp", "AdminDemo1")
TEACHER_PASSWORD = "TeacherDemo1"
STUDENT_PASSWORD = "StudentDemo1"
EMIS_PASSWORD = "password"
RUN = secrets.token_hex(3)
NOTIFY_WAIT_SECONDS = 150
TASHKENT = timezone(timedelta(hours=5))


@dataclass
class Config:
    """Where the stack lives."""

    api: str = "http://localhost:8000"
    hydra: str = "http://localhost:4444"
    mailpit: str = "http://localhost:8025"
    redis: str = "redis://localhost:6380/0"
    smtp_port: int = 2525
    emis_logins: list[str] = field(default_factory=list)
    student: str | None = None  # reuse this registered student instead of registering
    db_url: str = "postgresql://ihsp:ihsp@localhost:5433/ihsp"


class StepFailure(Exception):
    """A check of a step did not hold."""


class ApiError(StepFailure):
    """An HTTP response with an unexpected status."""

    def __init__(self, response: httpx.Response, wanted: str) -> None:
        """Keep the response for the report."""
        request = response.request
        body = response.text[:700].replace("\n", " ")
        super().__init__(
            f"{request.method} {request.url} -> {response.status_code} "
            f"(wanted {wanted}): {body}"
        )
        self.response = response


class Skip(Exception):
    """A step that cannot run in this environment."""


def check(condition: object, message: str) -> None:
    """Fail the step with ``message`` unless ``condition`` is truthy."""
    if not condition:
        raise StepFailure(message)


def ok(response: httpx.Response, *statuses: int) -> Any:
    """Return the JSON of a response with an accepted status (default 200/201/202/204)."""
    wanted = statuses or (200, 201, 202, 204)
    if response.status_code not in wanted:
        raise ApiError(response, "/".join(map(str, wanted)))
    if response.status_code == 204 or not response.content:
        return None
    if "json" not in response.headers.get("content-type", ""):
        return response.text
    return response.json()


def pkce() -> tuple[str, str]:
    """Return a PKCE verifier and its S256 challenge."""
    verifier = secrets.token_urlsafe(48)
    digest = hashlib.sha256(verifier.encode()).digest()
    return verifier, base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


# - - - Mailpit - - -


class Mailpit:
    """Reads the codes the backend mails to Mailpit."""

    def __init__(self, base_url: str) -> None:
        """Keep the base URL."""
        self.base = base_url.rstrip("/")

    async def known_ids(self) -> set[str]:
        """IDs of the messages present now (so a later wait sees only new ones)."""
        async with httpx.AsyncClient(timeout=15) as http:
            data = ok(
                await http.get(f"{self.base}/api/v1/messages", params={"limit": 200})
            )
        return {m["ID"] for m in data["messages"]}

    async def new_code(self, to: str, before: set[str], timeout: float = 25) -> str:
        """Wait for a message to ``to`` that is not in ``before``; return its 6-digit code."""
        deadline = time.monotonic() + timeout
        async with httpx.AsyncClient(timeout=15) as http:
            while time.monotonic() < deadline:
                data = ok(
                    await http.get(
                        f"{self.base}/api/v1/messages", params={"limit": 200}
                    )
                )
                for message in data["messages"]:
                    if message["ID"] in before:
                        continue
                    if any(a["Address"].lower() == to.lower() for a in message["To"]):
                        found = re.search(r"\b(\d{6})\b", message["Snippet"])
                        if found:
                            return found.group(1)
                await asyncio.sleep(0.5)
        raise StepFailure(f"no mail with a code for {to} in {timeout:.0f}s")


# - - - Sessions - - -


@dataclass
class Session:
    """A logged-in user: HTTP client with the bearer token."""

    name: str
    login: str
    token: str
    http: httpx.AsyncClient
    user_id: str = ""
    cookies: dict[str, str] = field(default_factory=dict)

    async def get(self, path: str, **kw: Any) -> httpx.Response:
        """GET an API path."""
        return await self.http.get(path, **kw)

    async def post(self, path: str, **kw: Any) -> httpx.Response:
        """POST an API path."""
        return await self.http.post(path, **kw)

    async def put(self, path: str, **kw: Any) -> httpx.Response:
        """PUT an API path."""
        return await self.http.put(path, **kw)

    async def patch(self, path: str, **kw: Any) -> httpx.Response:
        """PATCH an API path."""
        return await self.http.patch(path, **kw)


class Auth:
    """The scripted OAuth PKCE login: Hydra → /v1/id/login → code → /v1/oauth/token."""

    def __init__(self, cfg: Config, mail: Mailpit) -> None:
        """Keep the endpoints."""
        self.cfg = cfg
        self.mail = mail
        self.sessions: list[Session] = []

    async def login(
        self, app: str, login: str, password: str, recovery_email: str | None = None
    ) -> Session:
        """Log in through the whole OIDC dance; the client of the session keeps the token."""
        cfg = self.cfg
        verifier, challenge = pkce()
        redirect_uri = f"http://localhost:{APP_PORTS[app]}/auth/callback/"
        state = secrets.token_urlsafe(12)
        known = await self.mail.known_ids()
        async with httpx.AsyncClient(timeout=20, follow_redirects=False) as raw:
            query = {
                "client_id": app,
                "response_type": "code",
                "scope": SCOPE,
                "redirect_uri": redirect_uri,
                "state": state,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "audience": AUDIENCE,
            }
            start = await raw.get(f"{cfg.hydra}/oauth2/auth", params=query)
            if start.status_code not in (302, 303):
                raise ApiError(start, "302")
            challenge_id = parse_qs(urlparse(start.headers["location"]).query)[
                "login_challenge"
            ][0]
            sent = ok(
                await raw.post(
                    f"{cfg.api}/v1/id/login",
                    json={
                        "login_challenge": challenge_id,
                        "login": login,
                        "password": password,
                        "remember": False,
                    },
                ),
                200,
            )
            second = sent.get("second_factor")
            if second:
                address = recovery_email or f"{login}@ihsu.uz"
                code = await self.mail.new_code(address, known)
                sent = ok(
                    await raw.post(
                        f"{cfg.api}/v1/id/login/otp",
                        json={
                            "login_challenge": challenge_id,
                            "login": login,
                            "code": code,
                            "ticket": second["ticket"],
                        },
                    ),
                    200,
                )
            check(sent.get("redirect_to"), f"login gave no redirect_to: {sent}")
            code = await self._follow_to_code(
                raw, sent["redirect_to"], redirect_uri, state
            )
            token = ok(
                await raw.post(
                    f"{cfg.api}/v1/oauth/token",
                    json={
                        "client_id": app,
                        "code": code,
                        "code_verifier": verifier,
                        "redirect_uri": redirect_uri,
                    },
                    headers={
                        "X-IHSP-Client": app,
                        "Origin": f"http://localhost:{APP_PORTS[app]}",
                    },
                ),
                200,
            )
        http = httpx.AsyncClient(
            base_url=cfg.api,
            timeout=30,
            headers={"Authorization": f"Bearer {token['access_token']}"},
        )
        session = Session(
            app, login, token["access_token"], http, cookies=dict(raw.cookies)
        )
        self.sessions.append(session)
        return session

    async def _follow_to_code(
        self, raw: httpx.AsyncClient, url: str, redirect_uri: str, state: str
    ) -> str:
        """Follow Hydra's redirects (consent included) until the callback URL."""
        for _ in range(10):
            if url.startswith(redirect_uri):
                params = parse_qs(urlparse(url).query)
                check(params.get("state", [""])[0] == state, f"state mismatch in {url}")
                check("code" in params, f"no code in the callback: {url}")
                return params["code"][0]
            if "consent_challenge=" in url:
                challenge = parse_qs(urlparse(url).query)["consent_challenge"][0]
                info = ok(
                    await raw.get(
                        f"{self.cfg.api}/v1/id/consent",
                        params={"consent_challenge": challenge},
                    ),
                    200,
                )
                if info.get("redirect_to"):
                    url = info["redirect_to"]
                    continue
                accepted = ok(
                    await raw.post(
                        f"{self.cfg.api}/v1/id/consent",
                        json={"consent_challenge": challenge, "accept": True},
                    ),
                    200,
                )
                url = accepted["redirect_to"]
                continue
            response = await raw.get(url)
            if response.status_code not in (302, 303):
                raise ApiError(response, "302 (OAuth redirect chain)")
            url = response.headers["location"]
        raise StepFailure("OAuth redirect chain did not end in the callback")

    async def close(self) -> None:
        """Close every session client."""
        for session in self.sessions:
            await session.http.aclose()


# - - - Telegram initData (mini app login) - - -


def signed_init_data(telegram_id: int, bot_token: str = DEV_BOT_TOKEN) -> str:
    """A Telegram mini app initData string signed with the bot token (HMAC method)."""
    user = json.dumps(
        {"id": telegram_id, "first_name": "Smoke", "username": f"smoke{telegram_id}"},
        separators=(",", ":"),
    )
    fields = {
        "auth_date": str(int(time.time())),
        "query_id": f"AAH{secrets.token_hex(6)}",
        "user": user,
    }
    check = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    fields["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(fields)


def minimal_pdf(text: str) -> bytes:
    """A tiny valid one-page PDF containing ``text``."""
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 144] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        None,
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    stream = f"BT /F1 18 Tf 20 70 Td ({text}) Tj ET".encode()
    objects[3] = b"<< /Length %d >>\nstream\n%s\nendstream" % (len(stream), stream)
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n%s\nendobj\n" % (number, body)
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    for offset in offsets:
        out += b"%010d 00000 n \n" % offset
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1,
        xref,
    )
    return bytes(out)


def day_range(days_back: int = 0, days_forward: int = 6) -> dict[str, str]:
    """Query parameters ``from``/``to`` around today (Tashkent)."""
    today = datetime.now(TASHKENT).date()
    return {
        "from": (today - timedelta(days=days_back)).isoformat(),
        "to": (today + timedelta(days=days_forward)).isoformat(),
    }


# - - - The smoke run - - -


class Smoke:
    """Runs the steps in order, shares state between them and prints the verdicts."""

    def __init__(self, cfg: Config) -> None:
        """Create the helpers; ``self.s`` is the state steps hand to each other."""
        self.cfg = cfg
        self.mail = Mailpit(cfg.mailpit)
        self.auth = Auth(cfg, self.mail)
        self.redis = aioredis.from_url(cfg.redis, decode_responses=True)
        self.results: list[tuple[str, str, str]] = []
        self.s: dict[str, Any] = {}
        self.admin: Session
        self.student: Session
        self.teacher: Session

    # runner -------------------------------------------------------------

    async def step(self, name: str, fn: Callable[[], Awaitable[str | None]]) -> None:
        """Run one step; print PASS/FAIL/SKIP with detail and keep the verdict."""
        started = time.monotonic()
        try:
            detail = await fn()
            verdict, text = "PASS", detail or ""
        except Skip as skip:
            verdict, text = "SKIP", str(skip)
        except StepFailure as failure:
            verdict, text = "FAIL", str(failure)
        except Exception as exc:  # noqa: BLE001 - a crashed step is a failed step
            trace = traceback.format_exc(limit=3).strip().splitlines()[-4:]
            verdict, text = "FAIL", f"{type(exc).__name__}: {exc} | " + " / ".join(
                trace
            )
        elapsed = time.monotonic() - started
        self.results.append((verdict, name, text))
        suffix = f" - {text}" if text else ""
        print(f"{verdict:4} {name} ({elapsed:.1f}s){suffix}", flush=True)

    def need(self, *keys: str) -> None:
        """Skip the step when an earlier step did not produce its input."""
        missing = [key for key in keys if key not in self.s]
        if missing:
            raise Skip(f"needs {', '.join(missing)} from an earlier failed step")

    # steps: infrastructure and auth ---------------------------------------

    async def health(self) -> str:
        """Health, readiness and OIDC discovery."""
        async with httpx.AsyncClient(timeout=15) as http:
            health = ok(await http.get(f"{self.cfg.api}/health"))
            check(health.get("status") == "ok", f"health: {health}")
            ready = ok(await http.get(f"{self.cfg.api}/ready"))
            check(all(ready["checks"].values()), f"ready: {ready}")
            oidc = ok(
                await http.get(f"{self.cfg.hydra}/.well-known/openid-configuration")
            )
            check(
                oidc["issuer"].endswith("/"),
                f"issuer without trailing slash: {oidc['issuer']}",
            )
            jwks = ok(await http.get(oidc["jwks_uri"]))
            check(jwks["keys"], "Hydra publishes no keys")
        return f"issuer {oidc['issuer']}"

    async def admin_login(self) -> str:
        """Administrator: password, second factor code from Mailpit, PKCE token."""
        self.admin = await self.auth.login("admin", *ADMIN)
        me = ok(await self.admin.get("/v1/id/me"))
        check("admin" in me["roles"], f"roles: {me['roles']}")
        self.s["admin"] = me["id"]
        return f"{me['login']} roles={me['roles']}"

    async def register_student(self) -> str:
        """Register a fake EMIS student with the email code from Mailpit.

        EMIS registrations are limited to 10 per hour per IP, so the next free login is
        remembered in Redis (``smoke:emis-next``); when the limit is hit anyway, the
        student of the previous run is reused and this step is reported as skipped.
        """
        if self.cfg.student:
            self.s["student_login"] = self.cfg.student
            return f"reusing the registered student {self.cfg.student}"
        if self.cfg.emis_logins:
            candidates = self.cfg.emis_logins
        else:
            first = int(await self.redis.get(NEXT_STUDENT_KEY) or 2)
            candidates = [f"student{n:02d}" for n in range(first, 31) if n != 16]
        tried = []
        async with httpx.AsyncClient(timeout=30, base_url=self.cfg.api) as http:
            for emis_login in candidates[:4]:
                started = await http.post(
                    "/v1/id/register/emis",
                    json={"emis_login": emis_login, "emis_password": EMIS_PASSWORD},
                )
                if started.status_code == 429:
                    last = await self.redis.get(LAST_STUDENT_KEY)
                    if last:
                        self.s["student_login"] = last
                        raise Skip(
                            f"registration is rate limited ({started.json()['params']}); "
                            f"reusing {last} from the previous run"
                        )
                if started.status_code == 409:
                    tried.append(emis_login)
                    continue
                data = ok(started, 200)
                token = data["registration_token"]
                email = f"{emis_login}.{RUN}@example.org"
                before = await self.mail.known_ids()
                ok(
                    await http.post(
                        "/v1/id/register/email",
                        json={"registration_token": token, "email": email},
                    ),
                    200,
                    202,
                    204,
                )
                code = await self.mail.new_code(email, before)
                done = ok(
                    await http.post(
                        "/v1/id/register/complete",
                        json={
                            "registration_token": token,
                            "password": STUDENT_PASSWORD,
                            "email_code": code,
                            "confirm_import_match": True,
                            "login_challenge": None,
                        },
                    ),
                    200,
                    201,
                )
                self.s["emis_login"] = emis_login
                self.s["student_login"] = done["login"]
                number = int(re.sub(r"\D", "", emis_login) or 0)
                await self.redis.set(NEXT_STUDENT_KEY, number + 1)
                await self.redis.set(LAST_STUDENT_KEY, done["login"])
                profile = data["profile"]
                return (
                    f"{emis_login} -> login {done['login']}, group "
                    f"{profile['group_name']} (already linked, skipped: {tried})"
                )
        raise StepFailure(f"no free EMIS login among {candidates[:4]}: linked {tried}")

    async def student_login(self) -> str:
        """The registered student logs in through Hydra."""
        self.need("student_login")
        self.student = await self.auth.login(
            "sp", self.s["student_login"], STUDENT_PASSWORD
        )
        me = ok(await self.student.get("/v1/id/me"))
        check(me["roles"] == ["student"], f"roles: {me['roles']}")
        self.student.user_id = self.s["student"] = me["id"]
        return f"{me['login']}"

    async def link_telegram(self) -> str:
        """Link a fake Telegram account through the mini app login (signed initData)."""
        self.need("student_login")
        telegram_id = 910_000_000 + int(RUN, 16) % 1_000_000
        async with httpx.AsyncClient(timeout=20, base_url=self.cfg.api) as http:
            data = ok(
                await http.post(
                    "/v1/id/telegram/login",
                    json={
                        "init_data": signed_init_data(telegram_id),
                        "login": self.s["student_login"],
                        "password": STUDENT_PASSWORD,
                    },
                ),
                200,
            )
            check(data.get("linked") is True, f"not linked: {data}")
            status = ok(
                await http.post(
                    "/v1/id/telegram/status",
                    json={"init_data": signed_init_data(telegram_id)},
                ),
                200,
            )
            check(
                status["linked"] and status["login"] == self.s["student_login"],
                f"{status}",
            )
        self.s["telegram_id"] = telegram_id
        return f"telegram {telegram_id}"

    # steps: schedule and classwork ----------------------------------------

    async def teacher_login(self) -> str:
        """The teacher of the student's first lesson today logs in."""
        self.need("student")
        today = ok(await self.student.get("/v1/me/today"))
        lessons = today["lessons"]
        if not lessons:
            window = ok(
                await self.student.get("/v1/me/timetable", params=day_range(0, 7))
            )
            lessons = [item for item in window if item["status"] == "scheduled"]
        check(lessons, "the student has no lessons within a week (seed the demo data)")
        first = next((item for item in lessons if item.get("teacher")), None)
        check(first, "no lesson with a teacher")
        teacher = first["teacher"]
        login = f"{teacher['last_name']}.{teacher['first_name']}".lower()
        self.teacher = await self.auth.login("staff", login, TEACHER_PASSWORD)
        me = ok(await self.teacher.get("/v1/id/me"))
        check("teacher" in me["roles"], f"roles: {me['roles']}")
        self.teacher.user_id = self.s["teacher"] = me["id"]
        self.s["teacher_id"] = teacher["id"]
        check(
            me["id"] == teacher["id"], "logged-in teacher is not the lesson's teacher"
        )
        return f"{login}"

    async def student_today(self) -> str:
        """Today's lessons of the student (UF-WEB-01)."""
        self.need("student")
        today = ok(await self.student.get("/v1/me/today"))
        check({"now_or_next", "lessons"} <= set(today), f"keys: {list(today)}")
        lessons = today["lessons"]
        for lesson in lessons:
            check(
                lesson["subject"]["name"] and lesson["starts_at"], f"lesson: {lesson}"
            )
        self.s["today_lessons"] = lessons
        return f"{len(lessons)} lessons today, next: " + (
            f"period {today['now_or_next']['period']}"
            if today["now_or_next"]
            else "none"
        )

    async def student_timetable(self) -> str:
        """The week timetable of the student; lessons of my teacher are kept for later steps."""
        self.need("student", "teacher_id")
        items = ok(await self.student.get("/v1/me/timetable", params=day_range(2, 7)))
        check(items, "empty timetable for the week")
        mine = [
            i
            for i in items
            if i["teacher"]
            and i["teacher"]["id"] == self.s["teacher_id"]
            and i["status"] == "scheduled"
        ]
        today = datetime.now(TASHKENT).date().isoformat()
        upcoming = [i for i in mine if i["date"] >= today]
        check(
            len(upcoming) >= 2,
            f"need two upcoming lessons of the teacher, found {len(upcoming)}",
        )
        self.s["lesson"], self.s["lesson2"] = upcoming[0], upcoming[1]
        detail = ok(await self.student.get(f"/v1/me/lessons/{mine[0]['id']}"))
        check(detail["lesson"]["id"] == mine[0]["id"], "lesson detail id mismatch")
        return f"{len(items)} lessons in the window; {len(mine)} taught by the teacher"

    async def homework(self) -> str:
        """Teacher sets homework; student sees it, ticks it done and saves a note."""
        self.need("teacher", "student", "lesson")
        lesson_id = self.s["lesson"]["id"]
        text = f"Smoke homework {RUN}: exercises 1-3"
        ok(
            await self.teacher.put(
                f"/v1/staff/lessons/{lesson_id}/homework", json={"text": text}
            )
        )
        mine = None
        for status in ("upcoming", "later"):
            items = ok(
                await self.student.get("/v1/me/homework", params={"status": status})
            )
            mine = next((i for i in items if i["lesson_id"] == lesson_id), None)
            if mine:
                break
        check(mine and mine["text"] == text, "homework not listed for the student")
        check(mine["done_at"] is None, "homework already done")
        done = ok(
            await self.student.put(
                f"/v1/me/homework/{lesson_id}/done", json={"done": True}
            )
        )
        check(done["done_at"], f"not ticked: {done}")
        noted = ok(
            await self.student.put(
                f"/v1/me/homework/{lesson_id}/note", json={"note": f"note {RUN}"}
            )
        )
        check(noted["note"] == f"note {RUN}", f"note not saved: {noted}")
        again = ok(await self.student.get("/v1/me/homework", params={"status": "done"}))
        check(
            any(i["lesson_id"] == lesson_id for i in again),
            f"not in the done filter: {again}",
        )
        undone = ok(
            await self.student.put(
                f"/v1/me/homework/{lesson_id}/done", json={"done": False}
            )
        )
        check(undone["done_at"] is None, "untick failed")
        return f"lesson {lesson_id[:8]} text/done/note/untick"

    async def attendance(self) -> str:
        """Teacher submits attendance; a second submit with the old version conflicts."""
        self.need("teacher", "student", "lesson")
        lesson_id = self.s["lesson"]["id"]
        sheet = ok(await self.teacher.get(f"/v1/staff/lessons/{lesson_id}"))[
            "attendance"
        ]
        ids = {row["user_id"] for row in sheet["roster"]}
        check(self.s["student"] in ids, "the new student is missing from the roster")
        version = sheet["version"]
        saved = ok(
            await self.teacher.put(
                f"/v1/staff/lessons/{lesson_id}/attendance",
                json={
                    "absent": [self.s["student"]],
                    "present_unassigned": [],
                    "base_version": version,
                },
            )
        )
        check(
            saved["submitted"] and saved["version"] > version,
            f"not saved: {saved['version']}",
        )
        row = next(r for r in saved["roster"] if r["user_id"] == self.s["student"])
        check(row["absent"], "the student is not marked absent")
        stale = await self.teacher.put(
            f"/v1/staff/lessons/{lesson_id}/attendance",
            json={"absent": [], "present_unassigned": [], "base_version": version},
        )
        check(
            stale.status_code == 409,
            f"stale base_version gave {stale.status_code}: {stale.text[:300]}",
        )
        mine = ok(await self.student.get(f"/v1/me/lessons/{lesson_id}"))
        check(
            mine["my_attendance"] == "absent", f"student sees {mine['my_attendance']}"
        )
        overview = ok(await self.student.get("/v1/me/attendance"))
        fresh = ok(
            await self.teacher.put(
                f"/v1/staff/lessons/{lesson_id}/attendance",
                json={
                    "absent": [],
                    "present_unassigned": [],
                    "base_version": saved["version"],
                },
            )
        )
        check(fresh["version"] > saved["version"], "re-submit did not bump the version")
        return f"v{version}->v{saved['version']}->v{fresh['version']}, stale -> 409, overview keys {sorted(overview)[:4]}"

    async def link_teacher_telegram(self) -> str:
        """Link a fake Telegram account to the teacher (receives the lesson resources)."""
        self.need("teacher")
        telegram_id = 930_000_000 + int(RUN, 16) % 1_000_000
        login = f"{self.teacher.login}"
        async with httpx.AsyncClient(timeout=20, base_url=self.cfg.api) as http:
            linked = ok(
                await http.post(
                    "/v1/id/telegram/login",
                    json={
                        "init_data": signed_init_data(telegram_id),
                        "login": login,
                        "password": TEACHER_PASSWORD,
                    },
                ),
                200,
            )
        check(linked.get("linked") is True, f"teacher not linked: {linked}")
        self.s["teacher_telegram_id"] = telegram_id
        return f"telegram {telegram_id}"

    async def material(self) -> str:
        """Teacher adds a material to a lesson that starts in minutes (BOT-15 message awaited later).

        The reminder job messages the teacher and the head student 5 minutes before a
        lesson, within 30 minutes of its start, so the smoke creates its own lesson in a
        throwaway group and moves it to "starts in ~6.5 minutes" directly in the database
        (the one place where this script does not use HTTP). The group is archived and the
        lesson cancelled at the end.
        """
        self.need("admin", "teacher", "teacher_telegram_id", "lesson")
        group = ok(
            await self.admin.post(
                "/v1/admin/groups",
                json={
                    "name": f"SMK{RUN}",
                    "emis_group_id": None,
                    "current_semester": 3,
                },
            ),
            200,
            201,
        )
        self.s["smoke_group"] = group["id"]
        subject_id = self.s["lesson"]["subject"]["id"]
        start = datetime.now(TASHKENT).date() + timedelta(days=1)
        created: dict[str, Any] | None = None
        attempts: list[str] = []
        for offset in range(0, 14):
            day = start + timedelta(days=offset)
            if day.weekday() == 6:
                continue
            for period in (6, 5, 4, 3, 2, 1):
                response = await self.admin.post(
                    "/v1/admin/lessons",
                    json={
                        "date": day.isoformat(),
                        "period": period,
                        "subject_id": subject_id,
                        "teacher_id": self.s["teacher"],
                        "room_name": "101",
                        "audience": [{"group_id": group["id"], "subgroup": None}],
                        "topic": f"Smoke {RUN}",
                    },
                )
                if response.status_code in (200, 201):
                    created = response.json()
                    break
                attempts.append(f"{day}/{period}:{response.status_code}")
            if created:
                break
        check(created, f"could not create a lesson for the teacher: {attempts[:6]} ...")
        lesson_id = created["id"]
        self.s["smoke_lesson"] = lesson_id
        url = f"https://example.org/smoke-{RUN}"
        added = ok(
            await self.teacher.post(
                f"/v1/lessons/{lesson_id}/resources",
                json={
                    "role": "material",
                    "kind": "url",
                    "target_url": url,
                    "also_lesson_ids": [],
                },
            ),
            200,
            201,
        )
        check(
            added and added[0]["short_url"], f"no short url for the material: {added}"
        )
        listing = ok(await self.teacher.get(f"/v1/lessons/{lesson_id}/resources"))
        check(
            any(r["link_id"] == added[0]["link_id"] for r in listing),
            "material not listed",
        )
        self.s["material"] = added[0]
        # the same material is visible to students on their own lesson
        student_lesson = self.s["lesson"]["id"]
        also = ok(
            await self.teacher.post(
                f"/v1/lessons/{student_lesson}/resources",
                json={
                    "role": "material",
                    "kind": "url",
                    "target_url": url,
                    "also_lesson_ids": [],
                },
            ),
            200,
            201,
        )
        detail = ok(await self.student.get(f"/v1/me/lessons/{student_lesson}"))
        check(
            any(m["link_id"] == also[0]["link_id"] for m in detail["materials"]),
            "the student does not see the new material",
        )
        # move the smoke lesson to "starts in 6.5 minutes"
        starts = datetime.now(timezone.utc) + timedelta(minutes=6, seconds=30)
        ends = starts + timedelta(minutes=45)
        try:
            import asyncpg
        except ImportError as exc:
            raise Skip(
                "asyncpg is not installed; BOT-15 delivery is not checked"
            ) from exc
        try:
            connection = await asyncpg.connect(self.cfg.db_url)
            try:
                updated = await connection.execute(
                    "UPDATE academic.lessons SET starts_at = $1, ends_at = $2 WHERE id = $3",
                    starts,
                    ends,
                    UUID(lesson_id),
                )
            finally:
                await connection.close()
        except (OSError, asyncpg.PostgresError) as exc:
            raise Skip(
                f"cannot move the lesson in the database ({exc}); "
                "BOT-15 delivery is not checked"
            ) from exc
        check(updated == "UPDATE 1", f"lesson not moved: {updated}")
        self.s["material_url"] = added[0]["short_url"]
        self.s["material_added_at"] = time.time()
        return (
            f"lesson {lesson_id[:8]} in group SMK{RUN} on {created['date']} p{created['period']} "
            f"moved to start {starts:%H:%M:%S}Z; material {added[0]['short_url']}"
        )

    async def _upload(
        self,
        session: Session,
        name: str,
        purpose: str,
        data: bytes,
        content_type: str = "application/pdf",
    ) -> dict[str, Any]:
        """Presigned PUT upload + complete; return the file in its final state."""
        digest = base64.b64encode(hashlib.sha256(data).digest()).decode()
        created = ok(
            await session.post(
                "/v1/files",
                json={
                    "name": name,
                    "size": len(data),
                    "content_type": content_type,
                    "sha256_b64": digest,
                    "purpose": purpose,
                },
            ),
            200,
            201,
        )
        upload = created["upload"]
        async with httpx.AsyncClient(timeout=30) as storage:
            put = await storage.request(
                upload["method"], upload["url"], content=data, headers=upload["headers"]
            )
        if put.status_code not in (200, 201, 204):
            raise ApiError(put, "200 (presigned PUT to object storage)")
        file_id = created["file"]["id"]
        completed = ok(await session.post(f"/v1/files/{file_id}/complete"), 200, 202)
        check(
            completed["status"] in ("processing", "ready"),
            f"after complete: {completed['status']}",
        )
        deadline = time.monotonic() + 60
        current = completed
        while current["status"] == "processing" and time.monotonic() < deadline:
            await asyncio.sleep(1)
            current = ok(await session.get(f"/v1/files/{file_id}"))
        check(
            current["status"] == "ready",
            f"file ended as {current['status']} ({current.get('reject_reason')})",
        )
        return current

    async def files(self) -> str:
        """Upload a PDF through a presigned PUT; processing -> ready; storage usage grows."""
        self.need("student")
        before = ok(await self.student.get("/v1/me/storage"))
        pdf = minimal_pdf(f"Smoke {RUN} derivative of x squared is two x")
        ai_file = await self._upload(self.student, f"smoke-{RUN}.pdf", "ai_upload", pdf)
        link_file = await self._upload(self.student, f"share-{RUN}.pdf", "link", pdf)
        self.s["ai_file"], self.s["link_file"] = ai_file, link_file
        listed = ok(await self.student.get("/v1/me/files"))
        rows = listed["items"] if isinstance(listed, dict) else listed
        check(
            any(f["id"] == ai_file["id"] for f in rows),
            "uploaded file missing from /v1/me/files",
        )
        after = ok(await self.student.get("/v1/me/storage"))
        return (
            f"ai_upload ready (assistant_ready={ai_file['assistant_ready']}, "
            f"text_bytes={ai_file['text_bytes']}), link ready; storage {before} -> {after}"
        )

    async def links(self) -> str:
        """Create short links (URL and file) and resolve them."""
        self.need("student", "link_file")
        target = f"https://example.org/target-{RUN}"
        link = ok(
            await self.student.post(
                "/v1/links", json={"kind": "url", "target_url": target}
            ),
            200,
            201,
        )
        slug = link["slug"]
        async with httpx.AsyncClient(timeout=20, follow_redirects=False) as http:
            opened = await http.get(f"{self.cfg.api}/s/{slug}")
            check(
                opened.status_code in (200, 301, 302, 303, 307, 308),
                f"/s/{slug} -> {opened.status_code} {opened.text[:200]}",
            )
            where = opened.headers.get("location", "")
            body = opened.text
            check(
                target in where or target in body,
                f"target not in the answer: {where!r} {body[:200]!r}",
            )
            file_link = ok(
                await self.student.post(
                    "/v1/links",
                    json={"kind": "file", "file_id": self.s["link_file"]["id"]},
                ),
                200,
                201,
            )
            fopened = await http.get(f"{self.cfg.api}/s/{file_link['slug']}")
            check(
                fopened.status_code in (200, 302, 303, 307),
                f"file link -> {fopened.status_code} {fopened.text[:200]}",
            )
            missing = await http.get(f"{self.cfg.api}/s/nope{RUN}zz")
            check(
                missing.status_code == 404, f"unknown slug gave {missing.status_code}"
            )
        mine = ok(await self.student.get("/v1/me/links"))
        rows = mine["items"] if isinstance(mine, dict) else mine
        check(
            any(r["id"] == link["id"] for r in rows), "link missing from /v1/me/links"
        )
        self.s["short_link"] = link
        return f"/s/{slug} -> {opened.status_code}; file link -> {fopened.status_code}"

    async def rooms(self) -> str:
        """Administration lists rooms with PINs; the public room page needs the PIN."""
        self.need("admin")
        rooms = ok(await self.admin.get("/v1/admin/rooms"))
        check(rooms, "no rooms")
        room = rooms[0]
        check(
            re.fullmatch(r"\d{4,8}", room["pin"] or ""), f"strange PIN {room['pin']!r}"
        )
        async with httpx.AsyncClient(timeout=20, follow_redirects=False) as http:
            form = await http.get(f"{self.cfg.api}/r/{room['slug']}")
            check(form.status_code == 200, f"room page: {form.status_code}")
            check(room["pin"] not in form.text, "the PIN form leaks the PIN")
            wrong = await http.get(
                f"{self.cfg.api}/r/{room['slug']}", params={"pin": "0000"}
            )
            right = await http.get(
                f"{self.cfg.api}/r/{room['slug']}", params={"pin": room["pin"]}
            )
            check(right.status_code == 200, f"right PIN: {right.status_code}")
            check(
                right.text != form.text,
                "the page with the right PIN equals the PIN form",
            )
            check(
                wrong.text != right.text,
                "a wrong PIN shows the same page as the right one",
            )
            unknown = await http.get(
                f"{self.cfg.api}/r/no-such-room-{RUN}", params={"pin": "1234"}
            )
        check(unknown.status_code in (200, 404), f"unknown room: {unknown.status_code}")
        return (
            f"room {room['slug']} PIN {room['pin']}: form {form.status_code}, "
            f"wrong {wrong.status_code}, right {right.status_code}, {len(right.text)} bytes"
        )

    # steps: assistant, flash cards, LMS ------------------------------------

    async def assistant(self) -> str:
        """Fake LLM: a read tool runs at once, a write tool waits for approval."""
        self.need("student", "ai_file")
        chat = ok(
            await self.student.post("/v1/ai/chats", json={"assistant": "student"}),
            200,
            201,
        )
        chat_id = chat["id"]
        base = f"/v1/ai/chats/{chat_id}"
        # 1. read tool, with an attached file
        turn = ok(
            await self.student.post(
                f"{base}/messages",
                json={
                    "text": "What is my homework? See the attached file.",
                    "file_ids": [self.s["ai_file"]["id"]],
                },
            ),
            200,
            201,
        )
        check(turn["status"] == "done", f"read tool turn status {turn['status']}")
        calls = [c for m in turn["new_messages"] for c in m["tool_calls"]]
        check(
            any(
                c["tool"] == "get_homework"
                and c["access"] == "read"
                and c["status"] == "done"
                for c in calls
            ),
            f"no finished get_homework call: {calls}",
        )
        check(
            turn["new_messages"][-1]["role"] == "assistant"
            and turn["new_messages"][-1]["text"],
            "no final assistant text after the tool result",
        )
        # 2. write tool: approval, then approve
        turn = ok(
            await self.student.post(
                f"{base}/messages",
                json={"text": f"Make flash cards about derivatives {RUN}"},
            ),
            200,
            201,
        )
        check(
            turn["status"] == "awaiting_approval",
            f"write tool turn status {turn['status']}",
        )
        pending = [
            c
            for m in turn["new_messages"]
            for c in m["tool_calls"]
            if c["status"] == "pending_approval"
        ]
        check(
            len(pending) == 1
            and pending[0]["tool"] == "create_flashcard_set"
            and pending[0]["access"] == "write",
            f"pending: {pending}",
        )
        check(turn["chat"]["pending_approvals"] == 1, "pending_approvals != 1")
        before = ok(await self.student.get("/v1/me/flashcard-sets"))
        check(not any(RUN in s["title"] for s in before), "set created before approval")
        approved = ok(
            await self.student.post(f"{base}/tool-calls/{pending[0]['id']}/approve"),
            200,
            201,
        )
        check(approved["status"] == "done", f"after approve: {approved['status']}")
        after = ok(await self.student.get("/v1/me/flashcard-sets"))
        created = [s for s in after if RUN in s["title"]]
        check(
            len(created) == 1
            and created[0]["source"] == "ai"
            and created[0]["card_count"] == 3,
            f"set after approval: {created}",
        )
        self.s["ai_set"] = created[0]
        # 3. write tool: reject
        turn = ok(
            await self.student.post(
                f"{base}/messages", json={"text": f"Another flash set {RUN}-reject"}
            ),
            200,
            201,
        )
        pending = [
            c
            for m in turn["new_messages"]
            for c in m["tool_calls"]
            if c["status"] == "pending_approval"
        ]
        check(len(pending) == 1, f"second write tool did not wait: {turn['status']}")
        rejected = ok(
            await self.student.post(
                f"{base}/tool-calls/{pending[0]['id']}/reject", json={}
            ),
            200,
            201,
        )
        check(rejected["status"] == "done", f"after reject: {rejected['status']}")
        final = ok(await self.student.get("/v1/me/flashcard-sets"))
        check(
            len([s for s in final if RUN in s["title"]]) == 1,
            "rejected call created a set",
        )
        usage = ok(await self.student.get("/v1/ai/usage"))
        chats = ok(
            await self.student.get("/v1/ai/chats", params={"assistant": "student"})
        )
        check(
            any(c["id"] == chat_id for c in chats["items"]),
            "chat missing from the list",
        )
        self.s["chat_id"] = chat_id
        return f"chat {chat_id[:8]}: read ok, write approved, write rejected; usage {json.dumps(usage)[:120]}"

    async def flashcards(self) -> str:
        """Study a set card by card, create a manual set, share it publicly."""
        self.need("student", "ai_set")
        manual = ok(
            await self.student.post(
                "/v1/me/flashcard-sets",
                json={
                    "title": f"Manual {RUN}",
                    "description": None,
                    "cards": [{"front": f"q{i}", "back": f"a{i}"} for i in range(1, 5)],
                },
            ),
            200,
            201,
        )
        check(
            manual["card_count"] == 4 and manual["source"] == "manual",
            f"manual set: {manual}",
        )
        set_id = manual["id"]
        seen = 0
        state = ok(await self.student.get(f"/v1/me/flashcard-sets/{set_id}/study"))
        first_counts = state["counts"]
        check(state["card"], f"nothing to study: {state}")
        while state["card"] and seen < 10:
            seen += 1
            rating = ("again", "hard", "medium", "easy")[seen % 4]
            state = ok(
                await self.student.post(
                    f"/v1/me/flashcards/{state['card']['id']}/review",
                    json={"rating": rating},
                )
            )
        check(seen >= 4, f"only {seen} reviews before the session ended")
        sets = ok(await self.student.get("/v1/me/flashcard-sets"))
        mine = next(s for s in sets if s["id"] == set_id)
        share = ok(
            await self.student.post(
                "/v1/shares",
                json={
                    "kind": "flashcard_set",
                    "target_id": set_id,
                    "share_mode": "snapshot",
                },
            ),
            200,
            201,
        )
        async with httpx.AsyncClient(timeout=20) as http:
            public = ok(
                await http.get(f"{self.cfg.api}/v1/public/shares/{share['slug']}")
            )
        check(public, "public share is empty")
        # the AI set studies too
        ai_state = ok(
            await self.student.get(
                f"/v1/me/flashcard-sets/{self.s['ai_set']['id']}/study"
            )
        )
        check(ai_state["card"], "AI set has no card to study")
        return (
            f"{seen} reviews (start {first_counts}, now due_today={mine['due_today']}), "
            f"share /s/{share['slug']} public"
        )

    async def lms(self) -> str:
        """Admin builds a course (section, step with text and test), publishes; student does an attempt."""
        self.need("admin", "student")
        slug = f"smoke-{RUN}"
        course = ok(
            await self.admin.post(
                "/v1/lms/courses",
                json={
                    "title": f"Smoke course {RUN}",
                    "slug": slug,
                    "visibility": "public",
                },
            ),
            200,
            201,
        )
        cid = course["id"]
        outline = ok(
            await self.admin.post(
                f"/v1/lms/courses/{cid}/draft/outline",
                json={
                    "ops": [{"op": "add_section", "title": "Basics"}],
                    "lock_version": course["lock_version"],
                },
            )
        )
        section_id = outline["outline"][0]["id"]
        step = ok(
            await self.admin.post(
                f"/v1/lms/courses/{cid}/steps",
                json={"section_id": section_id, "title": "Arithmetic"},
            ),
            200,
            201,
        )
        step_id = step["step_id"]
        test_block = {
            "id": "",
            "type": "test",
            "config": {
                "max_attempts": None,
                "passing_score_pct": 60,
                "shuffle_questions": False,
                "shuffle_options": False,
                "pool_size": None,
                "time_limit_sec": None,
                "cooldown_sec": None,
                "show_answers": "after_submit",
            },
            "questions": [
                {
                    "id": "",
                    "type": "single",
                    "prompt": "2 + 2 = ?",
                    "points": 1,
                    "explanation": None,
                    "options": [
                        {"id": "", "text": "4", "correct": True, "pinned": False},
                        {"id": "", "text": "5", "correct": False, "pinned": False},
                    ],
                },
                {
                    "id": "",
                    "type": "number",
                    "prompt": "3 * 3 = ?",
                    "points": 1,
                    "explanation": None,
                    "answer": {"value": 9, "tolerance": 0},
                },
            ],
        }
        saved = ok(
            await self.admin.put(
                f"/v1/lms/steps/{step_id}/draft",
                json={
                    "content": {
                        "title": "Arithmetic",
                        "blocks": [
                            {
                                "id": "",
                                "type": "text",
                                "markdown": f"# Smoke {RUN}\n\nAdd and multiply.",
                            },
                            test_block,
                        ],
                    },
                    "lock_version": step["lock_version"],
                },
            )
        )
        blocks = saved["content"]["blocks"]
        check(all(b["id"] for b in blocks), "the server did not assign block ids")
        draft = ok(await self.admin.get(f"/v1/lms/courses/{cid}/draft"))
        check(
            draft["pending_count"] >= 1,
            f"nothing pending before publish: {draft['pending_count']}",
        )
        version = ok(
            await self.admin.post(
                f"/v1/lms/courses/{cid}/publish",
                json={"draft_seq": draft["draft_seq"], "note": "smoke"},
            )
        )
        check(version["number"] == 1, f"version: {version}")
        # student
        catalog = ok(
            await self.student.get(
                "/v1/lms/courses", params={"query": f"Smoke course {RUN}"}
            )
        )
        check(
            any(c["id"] == cid for c in catalog),
            f"published course not in the catalog: {catalog}",
        )
        enrolled = ok(
            await self.student.post(f"/v1/lms/courses/{cid}/enroll"), 200, 201
        )
        check(enrolled["enrolled"], "not enrolled")
        view = ok(await self.student.get(f"/v1/lms/courses/{cid}/steps/{step_id}"))
        test_view = next(b for b in view["blocks"] if b["type"] == "test")
        ok(await self.student.post(f"/v1/lms/steps/{step_id}/viewed"), 200, 201, 204)
        attempt = ok(
            await self.student.post(
                f"/v1/lms/steps/{step_id}/blocks/{test_view['id']}/attempts"
            ),
            200,
            201,
        )
        answers: dict[str, dict[str, Any]] = {}
        for question in attempt["questions"]:
            if question["type"] == "single":
                right = next(o for o in question["options"] if o["text"] == "4")
                answers[question["id"]] = {"option_ids": [right["id"]]}
            else:
                answers[question["id"]] = {"number": 9}
        ok(
            await self.student.put(
                f"/v1/lms/attempts/{attempt['id']}/answers", json={"answers": answers}
            )
        )
        result = ok(
            await self.student.post(f"/v1/lms/attempts/{attempt['id']}/submit"),
            200,
            201,
        )
        check(
            result["passed"] and result["score"] == result["max_score"] == 2,
            f"attempt result: {result}",
        )
        mine = ok(await self.student.get("/v1/lms/my-courses"))
        check(
            any(c["id"] == cid for c in mine["enrolled"]),
            "course missing from my-courses",
        )
        staff_view = ok(await self.admin.get(f"/v1/lms/courses/{cid}/students"))
        self.s["course_id"] = cid
        return (
            f"course {slug}: draft -> v{version['number']} -> attempt {result['score']}/"
            f"{result['max_score']} passed; students view {json.dumps(staff_view)[:80]}"
        )

    # steps: broadcast, MCP, calendar, administration ------------------------

    async def outbox(self, chat_id: int) -> list[dict[str, Any]]:
        """Messages the fake Telegram sent to ``chat_id`` (oldest first)."""
        lines = await self.redis.lrange(OUTBOX_KEY, 0, -1)
        entries = [json.loads(line) for line in lines]
        return [e for e in reversed(entries) if e.get("chat_id") == chat_id]

    async def link_admin_telegram(self) -> str:
        """Link a fake Telegram account to the administrator (needs the emailed code)."""
        self.need("admin")
        telegram_id = 920_000_000 + int(RUN, 16) % 1_000_000
        known = await self.mail.known_ids()
        async with httpx.AsyncClient(timeout=20, base_url=self.cfg.api) as http:
            first = ok(
                await http.post(
                    "/v1/id/telegram/login",
                    json={
                        "init_data": signed_init_data(telegram_id),
                        "login": ADMIN[0],
                        "password": ADMIN[1],
                    },
                ),
                200,
            )
            check(
                first.get("second_factor"),
                f"Administration was not asked for a code: {first}",
            )
            code = await self.mail.new_code(f"{ADMIN[0]}@ihsu.uz", known)
            linked = ok(
                await http.post(
                    "/v1/id/telegram/login",
                    json={
                        "init_data": signed_init_data(telegram_id),
                        "login": ADMIN[0],
                        "password": ADMIN[1],
                        "otp_code": code,
                    },
                ),
                200,
            )
        check(linked.get("linked") is True, f"admin not linked: {linked}")
        self.s["admin_telegram_id"] = telegram_id
        return f"telegram {telegram_id}"

    async def broadcast(self) -> str:
        """Administration sends a broadcast to the student's group (delivery awaited later)."""
        self.need("admin", "student", "telegram_id")
        profile = ok(await self.student.get("/v1/me/profile"))
        group_id = profile["group"]["id"]
        audience = {
            "everyone": False,
            "roles": [],
            "group_ids": [group_id],
            "semesters": [],
        }
        count = ok(
            await self.admin.post(
                "/v1/admin/broadcasts/audience-count", json={"audience": audience}
            )
        )
        check(count["count"] >= 1, f"audience is empty: {count}")
        text = f"Smoke broadcast {RUN}: classes continue as planned."
        created = ok(
            await self.admin.post(
                "/v1/admin/broadcasts",
                json={
                    "title": f"Smoke {RUN}",
                    "text": text,
                    "media_file_ids": [],
                    "audience": audience,
                },
            ),
            200,
            201,
        )
        preview = await self.admin.post(
            f"/v1/admin/broadcasts/{created['id']}/preview", json={}
        )
        check(
            preview.status_code in (200, 202, 204),
            f"preview: {preview.status_code} {preview.text[:200]}",
        )
        sent = ok(
            await self.admin.post(f"/v1/admin/broadcasts/{created['id']}/send"),
            200,
            202,
        )
        check(
            sent["status"]
            in ("sending", "scheduled", "queued", "sent", "done", "finished"),
            f"status after send: {sent['status']}",
        )
        self.s["broadcast"] = created["id"]
        self.s["broadcast_text"] = text
        self.s["broadcast_sent_at"] = time.time()
        return f"broadcast {created['id'][:8]} to group {profile['group']['name']} ({count['count']} users), status {sent['status']}"

    async def mcp(self) -> str:
        """Student MCP server through a connector token: tools/list and get_schedule."""
        self.need("student")
        scopes = ok(await self.student.get("/v1/id/mcp-scopes"))
        student_server = next(s for s in scopes["servers"] if s["server"] == "student")
        names = [s["scope"] for s in student_server["scopes"]]
        made = ok(
            await self.student.post(
                "/v1/id/me/connectors",
                json={
                    "server": "student",
                    "name": f"smoke {RUN}",
                    "scopes": names,
                    "course_ids": None,
                    "expires_in_days": 30,
                    "otp_code": None,
                },
            ),
            200,
            201,
        )
        token = made["token"]
        check(made["connector"]["token_prefix"], "connector without token prefix")
        url = f"{self.cfg.api}/mcp/student/"
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        }

        async def rpc(
            http: httpx.AsyncClient, ident: int, method: str, params: dict[str, Any]
        ) -> Any:
            response = await http.post(
                url,
                headers=headers,
                json={
                    "jsonrpc": "2.0",
                    "id": ident,
                    "method": method,
                    "params": params,
                },
            )
            body = ok(response, 200)
            check("error" not in body, f"{method}: {body}")
            return body["result"]

        async with httpx.AsyncClient(timeout=30) as http:
            anonymous = await http.post(
                url,
                headers={k: v for k, v in headers.items() if k != "Authorization"},
                json={"jsonrpc": "2.0", "id": 0, "method": "tools/list"},
            )
            check(
                anonymous.status_code == 401, f"no token gave {anonymous.status_code}"
            )
            init = await rpc(
                http,
                1,
                "initialize",
                {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                    "clientInfo": {"name": "smoke", "version": "1"},
                },
            )
            tools = await rpc(http, 2, "tools/list", {})
            tool_names = {t["name"] for t in tools["tools"]}
            check(
                {"get_schedule", "get_homework", "create_flashcard_set"} <= tool_names,
                f"tools: {sorted(tool_names)}",
            )
            result = await rpc(
                http, 3, "tools/call", {"name": "get_schedule", "arguments": {}}
            )
            check(not result.get("isError"), f"get_schedule failed: {result}")
            payload = result.get("structuredContent") or json.loads(
                result["content"][0]["text"]
            )
            lessons = payload.get("lessons", payload.get("result", {}).get("lessons"))
            check(lessons, f"get_schedule returned no lessons: {str(payload)[:300]}")
        listed = ok(await self.student.get("/v1/id/me/connectors"))
        check(
            any(c["id"] == made["connector"]["id"] for c in listed),
            "connector not listed",
        )
        ok(
            await self.student.http.delete(
                f"/v1/id/me/connectors/{made['connector']['id']}"
            ),
            200,
            204,
        )
        async with httpx.AsyncClient(timeout=30) as http:
            revoked = await http.post(
                url,
                headers=headers,
                json={"jsonrpc": "2.0", "id": 9, "method": "tools/list"},
            )
        check(revoked.status_code == 401, f"revoked token gave {revoked.status_code}")
        return (
            f"{init['serverInfo']['name']}: {len(tool_names)} tools, get_schedule -> "
            f"{len(lessons)} lessons; no token and revoked token -> 401"
        )

    async def ical(self) -> str:
        """The secret iCal feed lists the lessons."""
        self.need("student")
        token_url = ok(await self.student.post("/v1/me/calendar-token"), 200, 201)[
            "url"
        ]
        path = urlparse(token_url).path
        async with httpx.AsyncClient(timeout=20) as http:
            feed = await http.get(f"{self.cfg.api}{path}")
            bad = await http.get(f"{self.cfg.api}/ical/{'x' * 20}.ics")
        check(feed.status_code == 200, f"feed: {feed.status_code} {feed.text[:200]}")
        check(
            "text/calendar" in feed.headers.get("content-type", ""),
            feed.headers.get("content-type"),
        )
        check(
            feed.text.startswith("BEGIN:VCALENDAR")
            and feed.text.count("BEGIN:VEVENT") >= 5,
            f"calendar looks wrong: {feed.text[:200]!r}",
        )
        check(bad.status_code == 404, f"a wrong token gave {bad.status_code}")
        return f"{feed.text.count('BEGIN:VEVENT')} events at {path[:24]}...; wrong token -> 404"

    async def admin_views(self) -> str:
        """Administration: terms, dashboard, Student 360, sync history, groups, users."""
        self.need("admin", "student")
        terms = ok(await self.admin.get("/v1/admin/terms"))
        check(terms, "no terms")
        dashboard = ok(await self.admin.get("/v1/admin/dashboard"))
        check(
            {"today", "missing_attendance", "sync", "scheduled_broadcasts"}
            <= set(dashboard),
            f"dashboard keys: {list(dashboard)}",
        )
        check(
            dashboard["today"]["lessons"] > 0,
            f"no lessons today on the dashboard: {dashboard['today']}",
        )
        three_sixty = ok(
            await self.admin.get(f"/v1/admin/students/{self.s['student']}")
        )
        check(
            three_sixty["profile"]["login"] == self.s["student_login"],
            "wrong student in Student 360",
        )
        check(three_sixty["timetable_week"], "Student 360 without a timetable week")
        groups = ok(await self.admin.get("/v1/admin/groups/stats"))
        users = ok(await self.admin.get("/v1/admin/users", params={"limit": 5}))
        audit = ok(await self.admin.get("/v1/admin/audit", params={"limit": 5}))
        subjects = ok(await self.admin.get("/v1/admin/subjects"))
        return (
            f"{len(terms)} term(s), lessons today {dashboard['today']['lessons']}, "
            f"360 keys {sorted(three_sixty)[:5]}, {len(subjects)} subjects, audit/users ok"
        )

    async def sync(self) -> str:
        """Administration syncs one student at once and starts a full run (spread over ~20 min)."""
        self.need("admin", "student")
        me = ok(await self.student.get("/v1/me/profile"))
        one = await self.admin.post(
            "/v1/admin/sync/run", json={"user_id": self.s["student"]}
        )
        check(
            one.status_code == 202, f"single sync: {one.status_code} {one.text[:200]}"
        )
        deadline = time.monotonic() + 40
        synced = me["synced_at"]
        while time.monotonic() < deadline:
            synced = ok(await self.student.get("/v1/me/profile"))["synced_at"]
            if synced and synced != me["synced_at"]:
                break
            await asyncio.sleep(1)
        check(
            synced and synced != me["synced_at"],
            f"the student's profile was not synced (synced_at {me['synced_at']} -> {synced})",
        )
        runs = ok(await self.admin.get("/v1/admin/sync/runs", params={"limit": 5}))[
            "items"
        ]
        known = {r["id"] for r in runs}
        full = await self.admin.post("/v1/admin/sync/run")
        if full.status_code == 409:
            check(
                any(r["status"] == "running" for r in runs),
                f"409 without a running run: {full.text}",
            )
            note = "full run refused: one is already running (409)"
        else:
            check(
                full.status_code == 202,
                f"full sync: {full.status_code} {full.text[:200]}",
            )
            fresh: list[dict[str, Any]] = []
            for _ in range(20):
                items = ok(
                    await self.admin.get("/v1/admin/sync/runs", params={"limit": 5})
                )["items"]
                fresh = [r for r in items if r["id"] not in known]
                if fresh:
                    break
                await asyncio.sleep(1)
            check(fresh, "the full sync run did not appear in 20 s")
            note = f"full run {fresh[0]['id'][:8]} {fresh[0]['status']} (students are spread over ~20 min)"
        book = ok(await self.student.get("/v1/me/record-book"))
        ok(await self.student.get("/v1/me/grades"))
        return (
            f"profile synced at {synced}; {note}; record book keys {sorted(book)[:3]}"
        )

    async def moderation(self) -> str:
        """An anonymous report reaches the moderation queue; disabling the link stops it opening."""
        self.need("admin", "short_link")
        link = self.s["short_link"]
        async with httpx.AsyncClient(timeout=20, follow_redirects=False) as http:
            reported = await http.post(
                f"{self.cfg.api}/v1/public/reports",
                json={
                    "slug": link["slug"],
                    "reason": "other",
                    "comment": f"smoke {RUN}",
                },
            )
            check(
                reported.status_code in (200, 201, 202, 204),
                f"report: {reported.status_code} {reported.text[:200]}",
            )
            queue = ok(
                await self.admin.get(
                    "/v1/admin/moderation/queue", params={"limit": 100}
                )
            )
            row = next(
                (i for i in queue["items"] if i["link"]["id"] == link["id"]), None
            )
            check(
                row and row["reports"] >= 1,
                f"reported link missing from the queue ({len(queue['items'])} items)",
            )
            disabled = ok(
                await self.admin.post(
                    f"/v1/admin/links/{link['id']}/disable",
                    json={"reason": f"smoke {RUN}"},
                ),
                200,
            )
            check(disabled, "empty answer from disable")
            after = await http.get(f"{self.cfg.api}/s/{link['slug']}")
            check(
                after.status_code in (403, 404, 410),
                f"disabled link still opens: {after.status_code}",
            )
        return f"report queued ({row['reports']}), disabled link -> {after.status_code}"

    # steps: boundaries and sweep --------------------------------------------

    async def boundaries(self) -> str:
        """Roles are enforced: anonymous 401, student/teacher refused on admin and staff routes."""
        self.need("student", "teacher", "admin", "lesson")
        lesson_id = self.s["lesson"]["id"]
        async with httpx.AsyncClient(timeout=20, base_url=self.cfg.api) as anonymous:
            for path in (
                "/v1/me/today",
                "/v1/admin/dashboard",
                "/v1/staff/today",
                "/v1/notifications",
            ):
                response = await anonymous.get(path)
                check(
                    response.status_code == 401,
                    f"anonymous {path} -> {response.status_code}",
                )
        expected_403 = [
            (self.student, "get", "/v1/admin/dashboard"),
            (self.student, "get", "/v1/admin/users"),
            (self.student, "get", "/v1/staff/today"),
            (self.student, "put", f"/v1/staff/lessons/{lesson_id}/attendance"),
            (self.teacher, "get", "/v1/admin/dashboard"),
            (self.teacher, "get", "/v1/admin/rooms"),
            (self.teacher, "post", "/v1/admin/sync/run"),
        ]
        for session, method, path in expected_403:
            kwargs = (
                {"json": {"absent": [], "base_version": 0}} if method == "put" else {}
            )
            response = await session.http.request(method, path, **kwargs)
            check(
                response.status_code == 403,
                f"{session.name} {method.upper()} {path} -> {response.status_code}: {response.text[:150]}",
            )
        teacher_other = ok(await self.teacher.get("/v1/staff/groups"))
        check(isinstance(teacher_other, list), "staff groups is not a list")
        return f"anonymous 401 x4, {len(expected_403)} forbidden combinations -> 403"

    async def sweep(self) -> str:
        """Every parameterless GET route of the OpenAPI schema answers without a server error."""
        self.need("student", "teacher", "admin")
        async with httpx.AsyncClient(timeout=20) as http:
            schema = ok(await http.get(f"{self.cfg.api}/openapi.json"))
        skipped_prefixes = (
            "/internal",
            "/v1/oauth",
            "/v1/id/logout",
            "/v1/id/activation",
            "/v1/id/consent",
            "/v1/id/login",
            "/v1/public",
        )
        checked = 0
        problems: list[str] = []
        odd: list[str] = []
        for path, item in sorted(schema["paths"].items()):
            op = item.get("get")
            if not op or "{" in path or path.startswith(skipped_prefixes):
                continue
            if any(p.get("required") for p in op.get("parameters", [])):
                continue
            if path.startswith("/v1/admin/"):
                session = self.admin
            elif path.startswith("/v1/staff/"):
                session = self.teacher
            else:
                session = self.student
            response = await session.get(path)
            checked += 1
            if response.status_code >= 500:
                problems.append(
                    f"{session.name} GET {path} -> {response.status_code} {response.text[:120]}"
                )
            elif response.status_code != 200:
                odd.append(f"{path}:{response.status_code}")
        check(not problems, "server errors: " + " | ".join(problems))
        return f"{checked} GET routes, no 5xx" + (f"; non-200: {odd}" if odd else "")

    async def account_security(self) -> str:
        """Refresh cookie, sessions, password change, e-mail OTP login, password recovery.

        Runs last for the smoke student and always leaves it with the demo password and
        without OTP, so the next run can reuse it.
        """
        self.need("student", "student_login")
        student = self.student
        me = ok(await student.get("/v1/id/me"))
        email = me["recovery_email"]
        client = {
            "X-IHSP-Client": "sp",
            "Origin": f"http://localhost:{APP_PORTS['sp']}",
        }
        # refresh cookie -> new access token
        check(student.cookies, "the token exchange set no refresh cookie")
        async with httpx.AsyncClient(
            timeout=20, base_url=self.cfg.api, cookies=student.cookies
        ) as raw:
            refreshed = ok(
                await raw.post(
                    "/v1/oauth/refresh", json={"client_id": "sp"}, headers=client
                ),
                200,
            )
        check(refreshed["access_token"], "refresh returned no token")
        sessions = ok(await student.get("/v1/id/me/sessions"))
        check(
            any(item["current"] for item in sessions),
            f"no current session in {sessions}",
        )
        activity = ok(await student.get("/v1/id/me/activity"))
        check(activity["items"], "empty security log")
        notes = [
            f"refresh ok, {len(sessions)} session(s), {len(activity['items'])} log entries"
        ]
        temporary = f"Tmp{RUN}Pass1"
        changed = False
        try:
            # e-mail OTP: enable, log in with a code, disable
            known = await self.mail.known_ids()
            asked = await student.post("/v1/id/me/otp/enable", json={"via_email": True})
            if asked.status_code == 429:  # five codes per hour: repeated runs hit it
                notes.append(
                    f"OTP part skipped, rate limited: {asked.json()['params']}"
                )
                with_otp = student
            else:
                ok(asked, 200, 202, 204)
                code = await self.mail.new_code(email, known)
                enabled = ok(
                    await student.post(
                        "/v1/id/me/otp/enable/confirm", json={"code": code}
                    ),
                    200,
                )
                check(enabled["otp_enabled"], "OTP not enabled")
                with_otp = await self.auth.login(
                    "sp",
                    self.s["student_login"],
                    STUDENT_PASSWORD,
                    recovery_email=email,
                )
                check(with_otp.token, "login with the e-mail code failed")
                disabled = ok(
                    await with_otp.post(
                        "/v1/id/me/otp/disable", json={"password": STUDENT_PASSWORD}
                    ),
                    200,
                )
                check(not disabled["otp_enabled"], "OTP not disabled")
                notes.append("OTP enable/login/disable ok")
            # change the password, then recover the old one with an e-mailed code
            ok(
                await with_otp.post(
                    "/v1/id/me/password",
                    json={
                        "current_password": STUDENT_PASSWORD,
                        "new_password": temporary,
                    },
                ),
                200,
                204,
            )
            changed = True
            try:
                await self.auth.login("sp", self.s["student_login"], STUDENT_PASSWORD)
            except ApiError as refused:
                check(
                    refused.response.status_code == 401, f"old password gave {refused}"
                )
            else:
                raise StepFailure("the old password still logs in after the change")
            known = await self.mail.known_ids()
            async with httpx.AsyncClient(timeout=20, base_url=self.cfg.api) as anon:
                ok(
                    await anon.post(
                        "/v1/id/recovery/password/request",
                        json={"login_or_email": self.s["student_login"]},
                    ),
                    200,
                    202,
                    204,
                )
                code = await self.mail.new_code(email, known)
                ok(
                    await anon.post(
                        "/v1/id/recovery/password/confirm",
                        json={
                            "login_or_email": self.s["student_login"],
                            "code": code,
                            "new_password": STUDENT_PASSWORD,
                        },
                    ),
                    200,
                    204,
                )
            changed = False
            again = await self.auth.login(
                "sp", self.s["student_login"], STUDENT_PASSWORD
            )
            check(again.token, "login with the recovered password failed")
            self.student = again  # the password change ended the old session
            notes.append("password change + recovery ok")
        finally:
            if changed:  # recovery failed: put the demo password back by hand
                try:
                    back = await self.auth.login(
                        "sp", self.s["student_login"], temporary
                    )
                    await back.post(
                        "/v1/id/me/password",
                        json={
                            "current_password": temporary,
                            "new_password": STUDENT_PASSWORD,
                        },
                    )
                except StepFailure:
                    notes.append(f"WARNING: the student password stayed {temporary}")
        return "; ".join(notes)

    # steps: deliveries and clean-up -------------------------------------------

    async def deliveries(self) -> str:
        """Wait for the Telegram messages the earlier steps caused (fake outbox in Redis)."""
        self.need("telegram_id", "broadcast_text", "admin_telegram_id")
        expected: dict[str, tuple[int, Callable[[str], bool]]] = {
            "broadcast -> student": (
                self.s["telegram_id"],
                lambda t: self.s["broadcast_text"][:20] in t,
            ),
            "broadcast preview -> admin": (
                self.s["admin_telegram_id"],
                lambda t: RUN in t,
            ),
        }
        if "material_url" in self.s:
            expected["lesson resources -> teacher"] = (
                self.s["teacher_telegram_id"],
                lambda t: self.s["material_url"] in t,
            )
        found: dict[str, dict[str, Any]] = {}
        deadline = time.monotonic() + NOTIFY_WAIT_SECONDS
        while time.monotonic() < deadline and len(found) < len(expected):
            for label, (chat_id, wanted) in expected.items():
                if label in found:
                    continue
                for entry in await self.outbox(chat_id):
                    if entry.get("kind") == "message" and wanted(
                        entry.get("text_html", "")
                    ):
                        found[label] = entry
                        break
            if len(found) < len(expected):
                await asyncio.sleep(3)
        missing = [label for label in expected if label not in found]
        check(
            not missing,
            f"no Telegram message for: {missing} within {NOTIFY_WAIT_SECONDS}s "
            f"(worker/scheduler running? check the logs)",
        )
        resources = found.get("lesson resources -> teacher")
        if resources:
            text = resources["text_html"]
            check(
                "101" in text
                and "pin=" in json.dumps(resources.get("buttons") or "") + text,
                f"resources message lacks the room link with PIN: {text[:300]}",
            )
        return "; ".join(
            f"{label} ({found[label]['text_html'][:60]!r})" for label in found
        )

    async def notifications(self) -> str:
        """The web notification centre lists the broadcast; read-all clears the counter."""
        self.need("student", "broadcast_text")
        deadline = time.monotonic() + 30
        items: list[dict[str, Any]] = []
        while time.monotonic() < deadline:
            page = ok(await self.student.get("/v1/notifications", params={"limit": 50}))
            items = page["items"]
            if any(i["type"] == "broadcast" for i in items):
                break
            await asyncio.sleep(2)
        check(
            any(i["type"] == "broadcast" for i in items),
            f"no broadcast notification: {[i['type'] for i in items]}",
        )
        count = ok(await self.student.get("/v1/notifications/unread-count"))
        ok(await self.student.post("/v1/notifications/read-all"), 200, 204)
        after = ok(await self.student.get("/v1/notifications/unread-count"))
        check(
            after["count"] == 0 if "count" in after else True,
            f"unread after read-all: {after}",
        )
        return f"{len(items)} notifications, unread {count} -> {after}"

    async def mail_inbound(self) -> str:
        """Mail sent to the student's mailbox through the inbound SMTP process becomes a notification."""
        self.need("student_login")
        try:
            with socket.create_connection(("localhost", self.cfg.smtp_port), timeout=2):
                pass
        except OSError as exc:
            raise Skip(
                f"no inbound SMTP on :{self.cfg.smtp_port} (start `scripts/dev.sh mail`): {exc}"
            ) from exc
        import smtplib
        from email.message import EmailMessage

        message = EmailMessage()
        message["From"] = "friend@example.org"
        message["To"] = f"{self.s['student_login']}@mail.ihsu.uz"
        message["Subject"] = f"Smoke mail {RUN}"
        message.set_content("Hello from the smoke test.")
        await asyncio.to_thread(self._send_mail, message)
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            page = ok(await self.student.get("/v1/notifications", params={"limit": 20}))
            if any(i["type"] == "mail" for i in page["items"]):
                return "mail notification arrived"
            await asyncio.sleep(3)
        raise StepFailure("no mail notification after 90 s")

    def _send_mail(self, message: Any) -> None:
        import smtplib

        with smtplib.SMTP("localhost", self.cfg.smtp_port, timeout=15) as smtp:
            smtp.send_message(message)

    async def cleanup(self) -> str:
        """Unlink the fake Telegram accounts, cancel the smoke lesson, archive its group."""
        self.need("admin")
        notes = []
        unlinked = 0
        for name in ("admin", "teacher", "student"):
            session = getattr(self, name, None)
            if session is None:
                continue
            try:
                links = ok(await session.get("/v1/id/me/telegram"))
                for link in links:
                    if (link["username"] or "").startswith("smoke"):
                        await session.http.delete(
                            f"/v1/id/me/telegram/{link['telegram_user_id']}"
                        )
                        unlinked += 1
            except StepFailure as failure:
                notes.append(f"{name} unlink skipped ({str(failure)[:60]})")
        notes.append(f"{unlinked} fake Telegram links removed")
        if "smoke_lesson" in self.s:
            cancelled = ok(
                await self.admin.patch(
                    f"/v1/admin/lessons/{self.s['smoke_lesson']}",
                    json={"status": "cancelled"},
                )
            )
            notes.append(f"lesson {cancelled['status']}")
        if "smoke_group" in self.s:
            archived = ok(
                await self.admin.patch(
                    f"/v1/admin/groups/{self.s['smoke_group']}",
                    json={"status": "archived"},
                )
            )
            notes.append(f"group {archived['status']}")
        return ", ".join(notes) or "nothing to clean"

    # run ---------------------------------------------------------------------

    async def run(self) -> int:
        """Run every step in order; return the process exit code."""
        steps: list[tuple[str, Callable[[], Awaitable[str | None]]]] = [
            ("infra: health, readiness, OIDC discovery", self.health),
            ("auth: admin PKCE login with email second factor", self.admin_login),
            ("registration: fake EMIS student + Mailpit code", self.register_student),
            ("auth: student PKCE login", self.student_login),
            ("telegram: student mini-app login links the account", self.link_telegram),
            ("student: today", self.student_today),
            ("auth: teacher PKCE login", self.teacher_login),
            ("student: timetable and lesson detail", self.student_timetable),
            ("homework: teacher sets, student ticks and notes", self.homework),
            ("attendance: submit, stale version -> 409", self.attendance),
            (
                "telegram: teacher mini-app login links the account",
                self.link_teacher_telegram,
            ),
            (
                "telegram: administrator mini-app login (code by email)",
                self.link_admin_telegram,
            ),
            ("materials: teacher adds material, lesson starts soon", self.material),
            ("files: presigned PUT, complete, processing -> ready", self.files),
            ("links: short link create and resolve", self.links),
            ("rooms: page with PIN", self.rooms),
            ("moderation: report a short link, admin disables it", self.moderation),
            (
                "assistant: fake LLM read tool, write tool approve/reject",
                self.assistant,
            ),
            ("flashcards: study, share", self.flashcards),
            ("lms: edit -> publish -> student attempt", self.lms),
            ("broadcast: send to a group", self.broadcast),
            ("mcp: student server via connector token", self.mcp),
            ("calendar: iCal feed", self.ical),
            ("admin: dashboard, Student 360, terms", self.admin_views),
            ("sync: single student and full run", self.sync),
            ("security: role boundaries", self.boundaries),
            ("sweep: every parameterless GET route", self.sweep),
            (
                "deliveries: Telegram outbox (broadcast, preview, lesson resources)",
                self.deliveries,
            ),
            ("notifications: web centre", self.notifications),
            ("mail: inbound SMTP -> notification", self.mail_inbound),
            (
                "identity: refresh, sessions, OTP, password change and recovery",
                self.account_security,
            ),
            ("cleanup: smoke lesson and group", self.cleanup),
        ]
        print(f"IHSP smoke run {RUN} against {self.cfg.api}", flush=True)
        try:
            for name, fn in steps:
                await self.step(name, fn)
        finally:
            await self.auth.close()
            await self.redis.aclose()
        failed = [r for r in self.results if r[0] == "FAIL"]
        skipped = [r for r in self.results if r[0] == "SKIP"]
        passed = len(self.results) - len(failed) - len(skipped)
        print(
            f"\n{passed} passed, {len(failed)} failed, {len(skipped)} skipped",
            flush=True,
        )
        for verdict, name, text in failed:
            print(f"  FAIL {name}: {text}")
        return 1 if failed else 0


def main() -> int:
    """Parse the arguments and run the smoke test."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--api", default=Config.api, help="API base URL (the `all` process)"
    )
    parser.add_argument("--hydra", default=Config.hydra, help="Hydra public URL")
    parser.add_argument("--mailpit", default=Config.mailpit, help="Mailpit HTTP URL")
    parser.add_argument(
        "--redis", default=Config.redis, help="Redis URL (fake Telegram outbox)"
    )
    parser.add_argument(
        "--db-url", default=Config.db_url, help="PostgreSQL DSN (one fixture update)"
    )
    parser.add_argument(
        "--smtp-port", type=int, default=Config.smtp_port, help="inbound SMTP port"
    )
    parser.add_argument("--student", help="reuse this registered student login")
    parser.add_argument(
        "--emis", nargs="*", default=[], help="EMIS logins to try for registration"
    )
    args = parser.parse_args()
    cfg = Config(
        api=args.api.rstrip("/"),
        hydra=args.hydra.rstrip("/"),
        mailpit=args.mailpit.rstrip("/"),
        redis=args.redis,
        db_url=args.db_url,
        smtp_port=args.smtp_port,
        emis_logins=args.emis,
        student=args.student,
    )
    return asyncio.run(Smoke(cfg).run())


if __name__ == "__main__":
    sys.exit(main())
