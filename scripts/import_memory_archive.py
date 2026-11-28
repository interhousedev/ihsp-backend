"""Import the Memory Archive (interhousedev/archive_bot) into one club's albums.

One-off operator script, never run by the app. Inputs are ``mongoexport`` dumps of
the archive collections ``categories``, ``events`` and ``media_files`` (JSON lines or
``--jsonArray``) and read-only credentials of the archive bucket:

    ARCHIVE_S3_ENDPOINT_URL, ARCHIVE_S3_BUCKET, ARCHIVE_S3_ACCESS_KEY,
    ARCHIVE_S3_SECRET_KEY

    uv run python scripts/import_memory_archive.py --categories categories.json \
        --events events.json --media media_files.json --club-id <uuid> \
        --actor-id <platform admin user uuid> [--event <archive event id>] [--dry-run]

Mapping: category -> top-level album (``archive:category:<id>``), event -> album
under it (``archive:event:<id>``), shown and unbanned IMAGE/VIDEO file -> media item
(``archive:file:<id>``) copied from ``<images_folder>/<file_name>``; the processing
job re-encodes it, so EXIF (GPS) is dropped. Hidden, banned, FILE-type and orphan
items are counted, not copied. Imported albums are ``members`` visibility until a
moderator opens them. Reruns skip what is already imported (idempotent on
``source_ref``). ``--dry-run`` reads only the export files and writes nothing.
"""

import argparse
import asyncio
import dataclasses
import hashlib
import json
import mimetypes
import os
import sys
import tempfile
from collections import Counter
from collections.abc import Awaitable, Callable, Iterable
from datetime import date, datetime
from pathlib import Path
from typing import Any, Protocol
from uuid import UUID

from app.modules.activities.domain.media import AlbumVisibility, MediaKind
from app.shared.actor import Actor, Role

KINDS = {"IMAGE": MediaKind.PHOTO, "VIDEO": MediaKind.VIDEO}
FALLBACK_TYPES = {MediaKind.PHOTO: "image/jpeg", MediaKind.VIDEO: "video/mp4"}

Fetch = Callable[[str, Path], Awaitable[None]]


class ImportService(Protocol):
    """The MediaService methods the import uses."""

    async def upsert_album(self, actor: Actor, club_id: UUID, **kw: Any) -> Any:
        """Create or update the album of one archive folder."""

    async def imported_media(self, actor: Actor, club_id: UUID, source_ref: str) -> Any:
        """The media already imported from `source_ref`, if any."""

    async def import_media(
        self, actor: Actor, club_id: UUID, album_id: UUID, **kw: Any
    ) -> tuple[Any, bool]:
        """Import one file; the flag says whether it was new."""


class Store(Protocol):
    """The MediaStore method the import uses."""

    async def store_path(
        self, *, club_id: UUID, name: str, path: str, content_type: str
    ) -> UUID:
        """Store a local file and return its file id."""


@dataclasses.dataclass
class Report:
    """Counts printed at the end of a run."""

    albums: int = 0
    copied: int = 0
    already: int = 0
    bytes: int = 0
    skipped: Counter[str] = dataclasses.field(default_factory=Counter)


def load_export(path: Path) -> list[dict[str, Any]]:
    """Read a mongoexport file: a JSON array or one document per line."""
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return []
    if text.startswith("["):
        return list(json.loads(text))
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def _oid(doc: dict[str, Any]) -> str:
    raw = doc.get("_id", doc.get("id"))
    if isinstance(raw, dict):
        raw = raw.get("$oid", raw.get("$uuid"))
    return str(raw)


def _date(raw: Any) -> date | None:
    if isinstance(raw, dict):
        raw = raw.get("$date")
        if isinstance(raw, dict):
            raw = int(raw["$numberLong"])
    if isinstance(raw, (int, float)):
        return datetime.fromtimestamp(raw / 1000).date()
    if isinstance(raw, str) and raw:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).date()
    return None


def _content_type(name: str, kind: MediaKind) -> str:
    guessed = mimetypes.guess_type(name)[0]
    return guessed or FALLBACK_TYPES[kind]


async def run_import(  # noqa: C901 - one linear pass over the archive
    *,
    categories: Iterable[dict[str, Any]],
    events: Iterable[dict[str, Any]],
    media: Iterable[dict[str, Any]],
    service: ImportService | None,
    store: Store | None,
    fetch: Fetch | None,
    actor: Actor,
    club_id: UUID,
    event_filter: str | None = None,
    dry_run: bool = False,
) -> Report:
    """Copy the archive into ``club_id``; with ``dry_run`` only count."""
    rep = Report()
    cats = {_oid(c): c for c in categories}
    evs = {_oid(e): e for e in events}
    if event_filter is not None:
        evs = {k: v for k, v in evs.items() if k == event_filter}
    cat_album: dict[str, UUID] = {}
    ev_album: dict[str, UUID] = {}

    async def album_of_category(cid: str) -> UUID | None:
        if cid in cat_album or dry_run or service is None:
            return cat_album.get(cid)
        cat = cats.get(cid)
        if cat is None:
            return None
        album = await service.upsert_album(
            actor,
            club_id,
            source_ref=f"archive:category:{cid}",
            title=str(cat.get("name") or "Archive"),
            visibility=AlbumVisibility.MEMBERS,
        )
        rep.albums += 1
        cat_album[cid] = album.id
        return album.id

    for eid, ev in evs.items():
        cid = str(ev.get("category_id") or "")
        if cid not in cats:
            rep.skipped["event_without_category"] += 1
            continue
        if dry_run or service is None:
            if cid not in cat_album:
                cat_album[cid] = club_id  # placeholder: counted once
                rep.albums += 1
            rep.albums += 1
            continue
        parent = await album_of_category(cid)
        album = await service.upsert_album(
            actor,
            club_id,
            source_ref=f"archive:event:{eid}",
            title=str(ev.get("name") or "Event"),
            parent_id=parent,
            description=ev.get("description") or None,
            event_date=_date(ev.get("date")),
            visibility=AlbumVisibility.MEMBERS,
        )
        rep.albums += 1
        ev_album[eid] = album.id

    for doc in media:
        fid = _oid(doc)
        eid = str(doc.get("event_id") or "")
        if eid not in evs:
            if event_filter is None:
                rep.skipped["orphan"] += 1
            continue
        if doc.get("is_banned", False):
            rep.skipped["banned"] += 1
            continue
        if not doc.get("is_showed", True):
            rep.skipped["hidden"] += 1
            continue
        kind = KINDS.get(str(doc.get("type") or ""))
        if kind is None:
            rep.skipped["not_photo_or_video"] += 1
            continue
        if eid not in ev_album and not dry_run:
            rep.skipped["event_without_category"] += 1
            continue
        ref = f"archive:file:{fid}"
        if dry_run or service is None or store is None or fetch is None:
            rep.copied += 1
            continue
        if await service.imported_media(actor, club_id, ref) is not None:
            rep.already += 1
            continue
        name = str(doc["file_name"])
        key = f"{evs[eid]['images_folder']}/{name}"
        with tempfile.TemporaryDirectory(prefix="archive-") as tmp:
            path = Path(tmp) / name
            await fetch(key, path)
            data = path.read_bytes()
            file_id = await store.store_path(
                club_id=club_id,
                name=str(doc.get("original_name") or name),
                path=str(path),
                content_type=_content_type(name, kind),
            )
        _, created = await service.import_media(
            actor,
            club_id,
            ev_album[eid],
            source_ref=ref,
            kind=kind,
            original_file_id=file_id,
            byte_size=len(data),
            sha256_hex=hashlib.sha256(data).hexdigest(),
        )
        if created:
            rep.copied += 1
            rep.bytes += len(data)
        else:
            rep.already += 1
    return rep


def _s3_fetch(session: Any) -> Fetch:
    endpoint = os.environ["ARCHIVE_S3_ENDPOINT_URL"]
    bucket = os.environ["ARCHIVE_S3_BUCKET"]
    access = os.environ["ARCHIVE_S3_ACCESS_KEY"]
    secret = os.environ["ARCHIVE_S3_SECRET_KEY"]

    async def fetch(key: str, dest: Path) -> None:
        async with session.create_client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=access,
            aws_secret_access_key=secret,
        ) as s3:
            obj = await s3.get_object(Bucket=bucket, Key=key)
            async with obj["Body"] as body:
                with dest.open("wb") as out:
                    while chunk := await body.read(1 << 20):
                        out.write(chunk)

    return fetch


async def _run(a: argparse.Namespace) -> Report:
    docs = {
        "categories": load_export(a.categories),
        "events": load_export(a.events),
        "media": load_export(a.media),
    }
    actor = Actor(user_id=a.actor_id, roles=frozenset({Role.SU}))
    if a.dry_run:
        return await run_import(
            **docs,
            service=None,
            store=None,
            fetch=None,
            actor=actor,
            club_id=a.club_id,
            event_filter=a.event,
            dry_run=True,
        )
    from app.bootstrap.adapters.activities_media import FilesMediaStore
    from app.bootstrap.common import build_container
    from app.interfaces.jobs.broker import broker
    from app.settings import load_settings

    from aiobotocore.session import get_session

    fetch = _s3_fetch(get_session())
    await broker.startup()
    container = await build_container(load_settings(), process="cli")
    try:
        svc = container.activities.media
        return await run_import(
            **docs,
            service=svc,
            store=FilesMediaStore(container.files.public),
            fetch=fetch,
            actor=actor,
            club_id=a.club_id,
            event_filter=a.event,
        )
    finally:
        await container.close()
        await broker.shutdown()


def main() -> int:
    """Parse the arguments, run the import and print the counts as JSON."""
    p = argparse.ArgumentParser(
        description="Import the Memory Archive into a club's albums."
    )
    p.add_argument("--categories", type=Path, required=True)
    p.add_argument("--events", type=Path, required=True)
    p.add_argument("--media", type=Path, required=True, help="media_files export")
    p.add_argument("--club-id", type=UUID, required=True, help="owning club")
    p.add_argument(
        "--actor-id", type=UUID, required=True, help="platform admin running it"
    )
    p.add_argument("--event", help="import only this archive event id")
    p.add_argument("--dry-run", action="store_true", help="count, write nothing")
    rep = asyncio.run(_run(p.parse_args()))
    out = dataclasses.asdict(rep)
    out["skipped"] = dict(rep.skipped)
    json.dump(out, sys.stdout, indent=1)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
