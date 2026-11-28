"""Memory Archive import: mapping, skip rules, dry run and idempotent rerun."""

import hashlib
import importlib.util
import sys
from datetime import date
from pathlib import Path
from types import ModuleType
from typing import Any

from app.modules.activities.domain.club import Club
from app.modules.activities.domain.media import AlbumVisibility, MediaKind
from app.shared.actor import Actor
from tests.fakes.activities.world import ActivitiesWorld

ROOT = Path(__file__).resolve().parents[3]
FIX = ROOT / "tests/activities/fixtures/archive"
E1 = "0190a000-0000-7000-8000-0000000000e1"
E2 = "0190a000-0000-7000-8000-0000000000e2"
CAT = "0190a000-0000-7000-8000-000000000001"


def _script() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "import_memory_archive", ROOT / "scripts/import_memory_archive.py"
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _docs(mod: ModuleType) -> dict[str, Any]:
    return {
        "categories": mod.load_export(FIX / "categories.json"),
        "events": mod.load_export(FIX / "events.json"),
        "media": mod.load_export(FIX / "media_files.json"),
    }


class _Bucket:
    def __init__(self) -> None:
        self.keys: list[str] = []

    async def fetch(self, key: str, dest: Path) -> None:
        self.keys.append(key)
        dest.write_bytes(key.encode())


async def _run(
    mod: ModuleType,
    world: ActivitiesWorld,
    su: Actor,
    club: Club,
    bucket: _Bucket,
    **kw: Any,
) -> Any:  # the script's Report
    return await mod.run_import(
        **_docs(mod),
        service=world.services.media,
        store=world.media_store,
        fetch=bucket.fetch,
        actor=su,
        club_id=club.id,
        **kw,
    )


async def test_maps_albums_and_media_and_skips(
    world: ActivitiesWorld, club: Club, su: Actor
) -> None:
    mod = _script()
    bucket = _Bucket()
    rep = await _run(mod, world, su, club, bucket)
    assert rep.copied == 3 and rep.already == 0
    assert dict(rep.skipped) == {
        "event_without_category": 1,
        "hidden": 1,
        "banned": 1,
        "not_photo_or_video": 1,
        "orphan": 1,
    }
    assert sorted(bucket.keys) == [
        "5b1c3f2e-1a2b-4c3d-9e8f-000000000001/a1.jpg",
        "5b1c3f2e-1a2b-4c3d-9e8f-000000000001/a2.mp4",
        "5b1c3f2e-1a2b-4c3d-9e8f-000000000002/b1.png",
    ]
    albums = world.ports.albums
    cat = await albums.get_by_source_ref(f"archive:category:{CAT}")
    ev = await albums.get_by_source_ref(f"archive:event:{E1}")
    ev2 = await albums.get_by_source_ref(f"archive:event:{E2}")
    assert cat.title == "Graduation" and cat.parent_id is None
    assert ev.parent_id == cat.id and ev.title == "Prom 2024"
    assert ev.description == "Night" and ev.event_date == date(2024, 5, 25)
    assert ev2.event_date == date(2024, 5, 1) and ev2.description is None
    assert {a.visibility for a in (cat, ev, ev2)} == {AlbumVisibility.MEMBERS}

    svc = world.services.media
    video = await svc.imported_media(su, club.id, "archive:file:f2")
    photo = await svc.imported_media(su, club.id, "archive:file:f1")
    assert video.kind == MediaKind.VIDEO and photo.kind == MediaKind.PHOTO
    assert photo.album_id == ev.id and photo.imported and photo.uploaded_by is None
    data = b"5b1c3f2e-1a2b-4c3d-9e8f-000000000001/a1.jpg"
    assert photo.content_sha256 == hashlib.sha256(data).hexdigest()
    assert world.media_store.files[photo.original_file_id].name == "IMG_1.jpg"
    assert photo.id in world.media_kicker.kicked
    for skipped in ("f3", "f4", "f5", "f6"):
        assert await svc.imported_media(su, club.id, f"archive:file:{skipped}") is None


async def test_rerun_is_idempotent(
    world: ActivitiesWorld, club: Club, su: Actor
) -> None:
    mod = _script()
    await _run(mod, world, su, club, _Bucket())
    files_before = len(world.media_store.files)
    bucket = _Bucket()
    rep = await _run(mod, world, su, club, bucket)
    assert rep.copied == 0 and rep.already == 3 and bucket.keys == []
    assert len(world.media_store.files) == files_before


async def test_event_filter_and_dry_run(
    world: ActivitiesWorld, club: Club, su: Actor
) -> None:
    mod = _script()
    dry = await mod.run_import(
        **_docs(mod),
        service=None,
        store=None,
        fetch=None,
        actor=su,
        club_id=club.id,
        dry_run=True,
    )
    assert dry.copied == 3 and dry.albums == 3 and dry.bytes == 0
    assert not world.media_store.files

    bucket = _Bucket()
    rep = await _run(mod, world, su, club, bucket, event_filter=E2)
    assert rep.copied == 1 and rep.albums == 2 and dict(rep.skipped) == {}
    assert bucket.keys == ["5b1c3f2e-1a2b-4c3d-9e8f-000000000002/b1.png"]
