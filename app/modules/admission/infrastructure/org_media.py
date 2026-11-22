"""Logo and cover photo of each university and opportunity provider, stored once.

The shard files in ``catalog_data/org_media/*.json`` hold one object per
organisation: ``domain`` (the registrable website domain, the key of
``institutions.website_domain``), ``name``, ``aliases`` (the provider strings of
opportunities that belong to it), ``logo_url`` and ``cover_url`` (Wikimedia
Commons files or ``null``). ``apply_org_media`` copies these onto the institution
rows and onto the opportunities of the organisation without overwriting values
that staff have already set.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.modules.admission.domain.errors import MediaUnreachableError
from app.modules.admission.infrastructure.orm.catalog import InstitutionRow
from app.modules.admission.infrastructure.orm.opportunities import OpportunityRow
from app.modules.admission.ports.media_mirror import MediaMirror

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

DEFAULT_DIR = Path(__file__).parent / "catalog_data" / "org_media"


@dataclass(frozen=True, slots=True)
class OrgMedia:
    """The logo and cover of one organisation, shared by its catalog entries."""

    domain: str
    name: str
    aliases: tuple[str, ...]
    logo_url: str | None
    cover_url: str | None


@dataclass(frozen=True, slots=True)
class ApplyReport:
    """Rows changed by one ``apply_org_media`` run (counted in dry-run too)."""

    institutions_logo: int
    institutions_cover: int
    opportunities_logo: int


def normalize_domain(raw: object) -> str | None:
    """Lowercase website domain without ``www.``; ``None`` when empty."""
    if not isinstance(raw, str):
        return None
    domain = raw.strip().lower().removeprefix("www.")
    return domain or None


def _key(raw: str) -> str:
    return raw.strip().casefold()


def _parse(entry: dict[str, Any]) -> OrgMedia:
    domain = normalize_domain(entry.get("domain"))
    if domain is None:
        raise ValueError(f"org media entry without a domain: {entry!r}")
    name = str(entry.get("name") or "").strip()
    aliases = tuple(str(a) for a in entry.get("aliases") or [] if str(a).strip())
    logo = entry.get("logo_url")
    cover = entry.get("cover_url")
    return OrgMedia(
        domain=domain,
        name=name,
        aliases=aliases,
        logo_url=str(logo) if logo else None,
        cover_url=str(cover) if cover else None,
    )


def _merge(first: OrgMedia, other: OrgMedia) -> OrgMedia:
    """First non-null logo and cover win; aliases are the ordered union."""
    seen = {_key(a) for a in first.aliases}
    extra = tuple(a for a in other.aliases if _key(a) not in seen)
    return OrgMedia(
        domain=first.domain,
        name=first.name or other.name,
        aliases=first.aliases + extra,
        logo_url=first.logo_url or other.logo_url,
        cover_url=first.cover_url or other.cover_url,
    )


def load_org_media(directory: Path = DEFAULT_DIR) -> list[OrgMedia]:
    """Every organisation of every ``*.json`` shard, one entry per domain."""
    merged: dict[str, OrgMedia] = {}
    for path in sorted(directory.glob("*.json")):
        for raw in json.loads(path.read_text("utf-8")):
            media = _parse(raw)
            if media.domain in merged:
                merged[media.domain] = _merge(merged[media.domain], media)
            else:
                merged[media.domain] = media
    return sorted(merged.values(), key=lambda m: m.domain)


def by_domain(media: list[OrgMedia]) -> dict[str, OrgMedia]:
    """Organisations keyed by normalized website domain."""
    return {m.domain: m for m in media}


def by_alias(media: list[OrgMedia]) -> dict[str, OrgMedia]:
    """Organisations keyed by each alias and name, case-insensitively."""
    out: dict[str, OrgMedia] = {}
    for m in media:
        for label in (m.name, *m.aliases):
            if label.strip():
                out.setdefault(_key(label), m)
    return out


async def _stored(mirror: MediaMirror | None, url: str) -> str:
    """The storage copy of `url` when a mirror is given, else `url`."""
    return await mirror.mirror(url) if mirror is not None else url


async def _apply_institutions(
    session: AsyncSession,
    domains: dict[str, OrgMedia],
    dry_run: bool,
    mirror: MediaMirror | None,
) -> tuple[int, int]:
    """Fill empty institution logos and covers from their website domain."""
    logo = cover = 0
    institutions = await session.scalars(
        select(InstitutionRow).where(InstitutionRow.website_domain.is_not(None))
    )
    for row in institutions:
        org = domains.get(normalize_domain(row.website_domain) or "")
        if org is None:
            continue
        if org.logo_url and row.logo_url is None:
            logo += 1
            if not dry_run:
                row.logo_url = await _stored(mirror, org.logo_url)
        if org.cover_url and row.cover_url is None:
            cover += 1
            if not dry_run:
                row.cover_url = await _stored(mirror, org.cover_url)
    return logo, cover


async def _apply_opportunities(
    session: AsyncSession,
    aliases: dict[str, OrgMedia],
    dry_run: bool,
    mirror: MediaMirror | None,
) -> int:
    """Fill empty opportunity logos from the provider's organisation."""
    count = 0
    opportunities = await session.scalars(select(OpportunityRow))
    for opp in opportunities:
        payload = opp.payload or {}
        if payload.get("logo_url") is not None:
            continue
        provider = payload.get("provider")
        org = aliases.get(_key(provider)) if isinstance(provider, str) else None
        if org is None or org.logo_url is None:
            continue
        count += 1
        if not dry_run:
            opp.payload = {
                **payload,
                "logo_url": await _stored(mirror, org.logo_url),
            }
    return count


async def apply_org_media(
    session: AsyncSession,
    media: list[OrgMedia],
    *,
    dry_run: bool = False,
    mirror: MediaMirror | None = None,
) -> ApplyReport:
    """Fill empty institution and opportunity logos and covers; the caller commits.

    Existing non-null values are never overwritten. In dry-run nothing is changed
    but the counts are the ones a real run would report.
    """
    inst_logo, inst_cover = await _apply_institutions(
        session, by_domain(media), dry_run, mirror
    )
    opp_logo = await _apply_opportunities(session, by_alias(media), dry_run, mirror)
    return ApplyReport(inst_logo, inst_cover, opp_logo)


@dataclass(frozen=True, slots=True)
class MirrorReport:
    """Result of `mirror_existing_media`; `failed` lists `table:id:field: url`."""

    institutions: int
    opportunities: int
    failed: list[str]


async def _mirror_institutions(
    session: AsyncSession,
    mirror: MediaMirror,
    own: str,
    dry_run: bool,
    failed: list[str],
) -> int:
    """Mirror the logo and cover URLs of institutions; the count of URLs tried."""
    count = 0
    for row in await session.scalars(select(InstitutionRow)):
        for field in ("logo_url", "cover_url"):
            url = getattr(row, field)
            if not url or url.startswith(own):
                continue
            count += 1
            if dry_run:
                continue
            try:
                setattr(row, field, await mirror.mirror(url))
            except MediaUnreachableError:
                failed.append(f"institution:{row.id}:{field}: {url}")
    return count


async def _mirror_opportunities(
    session: AsyncSession,
    mirror: MediaMirror,
    own: str,
    dry_run: bool,
    failed: list[str],
) -> int:
    """Mirror the logo URLs of opportunities; the count of URLs tried."""
    count = 0
    for item in await session.scalars(select(OpportunityRow)):
        payload = item.payload or {}
        url = payload.get("logo_url")
        if not isinstance(url, str) or not url or url.startswith(own):
            continue
        count += 1
        if dry_run:
            continue
        try:
            item.payload = {**payload, "logo_url": await mirror.mirror(url)}
        except MediaUnreachableError:
            failed.append(f"opportunity:{item.id}:logo_url: {url}")
    return count


async def mirror_existing_media(
    session: AsyncSession, mirror: MediaMirror, *, dry_run: bool = False
) -> MirrorReport:
    """Replace every external institution and opportunity logo or cover URL.

    Unreachable URLs stay as they are and are listed in the report; the caller
    commits. In dry-run nothing is downloaded or changed and the counts are the
    URLs a real run would try.
    """
    own = mirror.own_prefix
    failed: list[str] = []
    inst = await _mirror_institutions(session, mirror, own, dry_run, failed)
    opp = await _mirror_opportunities(session, mirror, own, dry_run, failed)
    return MirrorReport(inst, opp, failed)
