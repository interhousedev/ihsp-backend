"""Research an event post into an opportunity draft (the bot intake of staff).

The text a counselor or helper sends is untrusted: links in it are fetched only
through `SafeFetcher` (https, public addresses, revalidated redirects), Telegram
links only as the public `t.me/s/<channel>/<post>` preview, and the model sees the
text and the pages as delimited data. Nothing is stored here; the bot submits the
confirmed draft through the opportunity service into the moderation queue.
"""

from __future__ import annotations

import datetime as dt
import html
import re
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass, field, fields
from typing import Any, Final, Protocol
from urllib.parse import urlsplit

from app.modules.admission.application.actor import AdmissionContext
from app.modules.admission.application.words import plain
from app.modules.admission.domain.errors import AdmissionForbiddenError
from app.modules.admission.infrastructure.ai.prompts import opportunity_intake as prompt
from app.modules.admission.ports.ai import PromptSource, StructuredAi
from app.shared.actor import Role
from app.shared.ai_tasks import AiTask
from app.shared.brand import with_brand
from app.shared.contracts.web_search import SearchCall, WebSearchGateway
from app.shared.safe_fetch import FetchPolicy, SafeFetcher, any_public_host

import structlog

log = structlog.get_logger(__name__)

KINDS: Final = ("exam", "certification", "course", "event", "recurring")
FIELDS: Final = ("title", "kind", "dates", "recurrence", "subjects", "provider")
MAX_TEXT: Final = 6000
MAX_LINKS: Final = 4
PAGE_CHARS: Final = 4000
_TOKENS: Final = 1400
_URL = re.compile(r"https?://[^\s<>\"'`]+", re.I)
_TG = re.compile(
    r"^https?://(?:www\.)?(?:t\.me|telegram\.me)/(?:s/)?([A-Za-z][A-Za-z0-9_]{4,31})"
    r"/(\d{1,9})/?$",
    re.I,
)
_TG_HOSTS: Final = frozenset({"t.me", "www.t.me", "telegram.me", "www.telegram.me"})
_RRULE = re.compile(
    r"^FREQ=(YEARLY|MONTHLY|WEEKLY)(;INTERVAL=([1-9]|1[0-2]))?"
    r"(;BYMONTH=([1-9]|1[0-2]))?(;BYMONTHDAY=([1-9]|[12]\d|3[01]))?$"
)
_TAGS = re.compile(r"<(script|style)[^>]*>.*?</\1>|<[^>]+>", re.I | re.S)
_MIME = frozenset({"text/html", "text/plain"})


class IntakeBlockedError(Exception):
    """A URL the fetch policy forbids."""


class _IntakeFetchFailed(Exception):
    """A page that could not be read."""


def build_intake_fetcher() -> SafeFetcher:
    """The fetcher of researched pages: https only, any public host, small bodies."""
    policy = FetchPolicy(
        schemes=frozenset({"https"}),
        ports=frozenset({443}),
        allowed_hosts=any_public_host,
        redirect_policy="revalidate_any",
        mime_allow_list=_MIME,
        max_bytes=1024 * 1024,
        total_timeout=8.0,
        connect_timeout=3.0,
        accept="text/html,text/plain;q=0.9",
    )
    return SafeFetcher(
        policy,
        unsafe=lambda details: IntakeBlockedError(details),
        failed=lambda details: _IntakeFetchFailed(details),
    )


class TaxonomySubjectLike(Protocol):
    """A subject of the opportunity taxonomy."""

    id: Any
    name: dict[str, str]


class _SubfieldLike(Protocol):
    id: Any
    name: dict[str, str]
    subjects: Sequence[TaxonomySubjectLike]


class TaxonomyFieldLike(Protocol):
    """A field of the taxonomy with its subfields and subjects."""

    id: Any
    name: dict[str, str]
    subfields: Sequence[_SubfieldLike]


@dataclass(slots=True)
class IntakeDraft:
    """The researched draft, JSON-friendly so the bot keeps it in its FSM data."""

    title: str = ""
    summary: str = ""
    provider: str = ""
    kind: str = "event"
    registration_deadlines: list[str] = field(default_factory=list)
    event_dates: list[str] = field(default_factory=list)
    recurrence: str = ""
    subject_ids: list[str] = field(default_factory=list)
    url: str = ""
    materials: list[dict[str, str]] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    blocked: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Return the draft as plain data."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> IntakeDraft:
        """Rebuild a draft kept as plain data."""
        names = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in names})


def may_submit(ctx: AdmissionContext) -> bool:
    """Staff, helpers with live grants and students may submit (all moderated)."""
    actor = ctx.admission
    return not actor.blocked and (
        actor.is_staff or actor.has_help_grants or Role.STUDENT in ctx.actor.roles
    )


def extract_links(text: str) -> list[str]:
    """The distinct links of a message, trailing punctuation removed."""
    seen: list[str] = []
    for match in _URL.finditer(text):
        url = match.group(0).rstrip(".,;:!?)]}»")
        if url not in seen:
            seen.append(url)
    return seen


def research_url(url: str) -> str | None:
    """The URL to fetch for a link: public post previews for Telegram, else itself.

    Telegram links other than a public channel post (private `t.me/c/...`,
    invite links, user profiles) return None: no account is ever used.
    """
    host = (urlsplit(url).hostname or "").lower()
    if host in _TG_HOSTS:
        match = _TG.match(url.split("?", 1)[0])
        if match is None:
            return None
        return f"https://t.me/s/{match.group(1)}/{match.group(2)}"
    return url


def page_text(body: bytes) -> str:
    """Visible text of a page, collapsed."""
    raw = body.decode("utf-8", errors="replace")
    text = html.unescape(_TAGS.sub(" ", raw))
    return " ".join(text.split())[:PAGE_CHARS]


def _wrap(tag: str, text: str, **attrs: str) -> str:
    clean = re.sub(rf"</?{tag}\b[^>]*>", "", text, flags=re.I)
    extra = "".join(f' {k}="{html.escape(v)}"' for k, v in attrs.items())
    return f"<{tag}{extra}>\n{clean}\n</{tag}>"


def subjects_of(taxonomy: Iterable[TaxonomyFieldLike]) -> dict[str, str]:
    """Subject id → `Field / Subfield / Subject` in English, for the prompt."""
    out: dict[str, str] = {}
    for fld in taxonomy:
        for sub in fld.subfields:
            for subject in sub.subjects:
                out[str(subject.id)] = " / ".join(
                    n.name.get("en") or next(iter(n.name.values()), "")
                    for n in (fld, sub, subject)
                )
    return out


def _dates(values: Iterable[Any], today: dt.date) -> list[str]:
    out: list[str] = []
    for value in values:
        try:
            day = dt.date.fromisoformat(str(value)[:10])
        except ValueError:
            continue
        if abs((day - today).days) <= 3 * 366 and day.isoformat() not in out:
            out.append(day.isoformat())
    return sorted(out)[: prompt.MAX_DATES]


def _https(url: Any, known: set[str]) -> str:
    text = str(url or "").strip()
    return text if text.startswith("https://") and text in known else ""


class OpportunityIntake:
    """Links, Exa and fetched pages, then one structured model call."""

    def __init__(
        self,
        ai: StructuredAi,
        prompts: PromptSource,
        *,
        web_search: WebSearchGateway | None = None,
        fetcher: SafeFetcher | None = None,
        profile_of: Any = None,
    ) -> None:
        """Keep the model, the prompts and the research tools."""
        self._ai = ai
        self._prompts = prompts
        self._search = web_search
        self._fetcher = fetcher or build_intake_fetcher()
        self._profile_of = profile_of

    async def research(
        self,
        ctx: AdmissionContext,
        text: str,
        *,
        locale: str,
        today: dt.date,
        taxonomy: Sequence[TaxonomyFieldLike],
    ) -> IntakeDraft:
        """Return a cleaned draft; `missing` names the fields still to ask."""
        if not may_submit(ctx):
            raise AdmissionForbiddenError(params={"permission": "opportunities:submit"})
        text = text.strip()[:MAX_TEXT]
        links = extract_links(text)
        known = set(links)
        blocked: list[str] = []
        sources: list[str] = []
        for link in links[:MAX_LINKS]:
            target = research_url(link)
            if target is None:
                blocked.append(link)
                continue
            try:
                self._fetcher.check(target)
                body = await self._fetcher.fetch(target)
            except IntakeBlockedError:
                blocked.append(link)
                continue
            except _IntakeFetchFailed as exc:
                log.info("opportunity_intake_fetch_failed", reason=str(exc)[:80])
                continue
            known.add(target)
            sources.append(_wrap("source", page_text(body.data), url=target))
        known.difference_update(blocked)  # a blocked link never reaches the draft
        sources += await self._web(text, locale, known)
        subjects = subjects_of(taxonomy)
        lines = [f"Today: {today.isoformat()}", f"Language: {locale}", "Subjects:"]
        lines += [f"- {sid}: {name}" for sid, name in subjects.items()]
        user = "\n".join(
            [*lines, _wrap("event_text", text), *sources]
        )  # data only, delimited
        data, _ = await self._ai.json(
            task=AiTask.ADMIT_OPPORTUNITY_INTAKE,
            system=with_brand(
                await self._prompts.text(
                    AiTask.ADMIT_OPPORTUNITY_INTAKE, "system", locale
                )
            ),
            user=user,
            schema_name=prompt.SCHEMA_NAME,
            schema=prompt.SCHEMA,
            max_tokens=_TOKENS,
        )
        draft = clean(data, known=known, subjects=set(subjects), today=today)
        draft.blocked = blocked
        return draft

    async def _web(self, text: str, locale: str, known: set[str]) -> list[str]:
        """Exa (through the shared limiter) for context; failures are ignored."""
        if self._search is None or self._profile_of is None:
            return []
        query = " ".join(_URL.sub(" ", text).split())[:200]
        if len(query) < 8:
            return []
        try:
            reply = await self._search.search(
                SearchCall(
                    query=query,
                    language=locale,
                    max_results=3,
                    explain=False,
                    profile=self._profile_of(AiTask.ADMIT_OPPORTUNITY_INTAKE),
                )
            )
        except Exception as exc:  # the web is extra context, never required
            log.info("opportunity_intake_search_failed", error=type(exc).__name__)
            return []
        out: list[str] = []
        for hit in reply.hits:
            if hit.url.startswith("https://"):
                known.add(hit.url)
                out.append(
                    _wrap("source", f"{hit.title}. {hit.snippet}"[:800], url=hit.url)
                )
        return out


def clean(
    data: dict[str, Any], *, known: set[str], subjects: set[str], today: dt.date
) -> IntakeDraft:
    """Keep only valid values from the model and list what is still missing."""
    kind = str(data.get("kind") or "")
    uncertain = {str(u) for u in data.get("uncertain") or [] if str(u) in FIELDS}
    recurrence = str(data.get("recurrence") or "").strip().upper()
    draft = IntakeDraft(
        title=plain(str(data.get("title") or ""))[:200],
        summary=plain(str(data.get("summary") or ""))[:1200],
        provider=plain(str(data.get("provider") or ""))[:200],
        kind=kind if kind in KINDS else "event",
        registration_deadlines=_dates(data.get("registration_deadlines") or [], today),
        event_dates=_dates(data.get("event_dates") or [], today),
        recurrence=recurrence if _RRULE.match(recurrence) else "",
        subject_ids=[
            s
            for s in dict.fromkeys(map(str, data.get("subject_ids") or []))
            if s in subjects
        ][: prompt.MAX_SUBJECTS],
    )
    draft.url = _https(data.get("main_url"), known) or next(
        (u for u in sorted(known) if u.startswith("https://")), ""
    )
    for raw in (data.get("materials") or [])[: prompt.MAX_LINKS]:
        url = _https(raw.get("url") if isinstance(raw, dict) else None, known)
        title = plain(str(raw.get("title") or "")) if isinstance(raw, dict) else ""
        if url and url != draft.url and title:
            draft.materials.append({"title": title[:200], "url": url})
    if kind not in KINDS:
        uncertain.add("kind")
    draft.missing = missing_fields(draft, uncertain)
    return draft


def missing_fields(draft: IntakeDraft, uncertain: set[str] | None = None) -> list[str]:
    """The fields to ask about, in the order the bot asks them."""
    out: list[str] = []
    if not draft.title:
        out.append("title")
    if "kind" in (uncertain or set()):
        out.append("kind")
    if draft.kind == "recurring":
        if not draft.recurrence:
            out.append("recurrence")
    elif not (draft.registration_deadlines or draft.event_dates) or "dates" in (
        uncertain or set()
    ):
        out.append("dates")
    if not draft.subject_ids or "subjects" in (uncertain or set()):
        out.append("subjects")
    return out
