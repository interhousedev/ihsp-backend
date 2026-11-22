"""Essay key administration: backup once, restore never overwrites, rotation."""

import dataclasses
import datetime as dt
import json
from uuid import UUID

from app.modules.admission.application.essay_keys import (
    ROTATE_TASK,
    STALE_AFTER,
    EssayKeyAdmin,
)
from app.modules.admission.domain.errors import (
    AdmissionForbiddenError,
    EssayKeysBackupInvalidError,
    EssayKeysBackupTakenError,
    EssayKeysRotationRunningError,
)
from app.modules.admission.infrastructure.essay_crypto import (
    AesGcmEssayCipher,
    MemoryEssayKeyStore,
    open_blob,
    seal_blob,
)
from app.modules.admission.infrastructure.essay_key_backup import (
    ScryptAesGcmBackupCodec,
)
from app.modules.admission.infrastructure.essay_keys_sql import Unreadable, move_blob
from app.modules.admission.ports.essay_crypto import EssayKey
from app.modules.admission.ports.essay_keys import (
    BackupBuilder,
    EssayKeyLedgerState,
    ResealResult,
    RotationFencedError,
    RotationProgress,
)
from app.modules.admission.ports.repositories import AuditEvent
from app.shared.actor import Actor, Role
from app.shared.ids import new_id
from tests.fakes.clock import FixedClock
from tests.fakes.tasks import FakeTaskKicker

import pytest

PASS = "correct horse battery staple"
ADMIN = Actor(user_id=new_id(), roles=frozenset({Role.ADMIN}))


class MemoryLedger:
    """In-memory `EssayKeyLedger` with the same lease and fencing rules."""

    def __init__(self) -> None:
        self.generation = 1
        self.exports: dict[int, tuple[dt.datetime, UUID]] = {}
        self.rotation = RotationProgress("idle", 0, 0, 0, None, None, None)
        self.events: list[AuditEvent] = []

    async def state(self) -> EssayKeyLedgerState:
        export = self.exports.get(self.generation)
        return EssayKeyLedgerState(
            self.generation,
            export[0] if export else None,
            export[1] if export else None,
            self.rotation,
        )

    async def export(
        self, actor_id: UUID, at: dt.datetime, build: BackupBuilder
    ) -> bytes:
        if self.rotation.state not in ("idle", "done"):
            raise EssayKeysRotationRunningError()
        if self.generation in self.exports:
            raise EssayKeysBackupTakenError()
        content, event = await build(self.generation)
        self.exports[self.generation] = (at, actor_id)
        self.events.append(event)
        return content

    async def start_rotation(
        self, run_id: UUID, actor_id: UUID, at: dt.datetime, stale_before: dt.datetime
    ) -> bool:
        r = self.rotation
        beat = r.heartbeat_at
        if r.state == "running" and beat is not None and beat >= stale_before:
            return False
        self.rotation = RotationProgress(
            "running", 0, 0, 0, at, None, actor_id, run_id=run_id, heartbeat_at=at
        )
        return True

    def _fenced(self, run_id: UUID, at: dt.datetime, **kw: object) -> bool:
        r = self.rotation
        if r.state != "running" or r.run_id != run_id:
            return False
        replaced = dataclasses.replace(r, heartbeat_at=at)
        self.rotation = dataclasses.replace(replaced, **kw)  # type: ignore[arg-type]
        return True

    async def heartbeat(self, run_id: UUID, at: dt.datetime) -> bool:
        return self._fenced(run_id, at)

    async def set_total(self, run_id: UUID, total: int, at: dt.datetime) -> bool:
        return self._fenced(run_id, at, total=total, done=0, unreadable=0)

    async def advance(self, run_id: UUID, unreadable: int, at: dt.datetime) -> bool:
        r = self.rotation
        return self._fenced(
            run_id, at, done=r.done + 1, unreadable=r.unreadable + unreadable
        )

    async def finish_rotation(self, run_id: UUID, at: dt.datetime) -> bool:
        if not self._fenced(run_id, at, state="done", finished_at=at):
            return False
        self.generation += 1
        return True

    async def fail_rotation(self, run_id: UUID, at: dt.datetime) -> bool:
        return self._fenced(run_id, at, state="failed", finished_at=at)

    async def audit(self, event: AuditEvent) -> None:
        self.events.append(event)


class MemoryResealer:
    """Blobs per (owner, record, column), moved with the production `move_blob`."""

    def __init__(self, ledger: MemoryLedger) -> None:
        self.ledger = ledger
        self.blobs: dict[tuple[UUID, UUID, str], bytes] = {}

    async def reseal(self, key: EssayKey, run_id: UUID) -> ResealResult:
        r = self.ledger.rotation
        if r.state != "running" or r.run_id != run_id:
            raise RotationFencedError()
        resealed = unreadable = 0
        for (owner, record, column), blob in list(self.blobs.items()):
            if owner != key.owner_id:
                continue
            moved = move_blob(key, record, column, blob)
            if isinstance(moved, Unreadable):
                unreadable += 1
            elif moved is not None:
                self.blobs[(owner, record, column)] = moved
                resealed += 1
        return ResealResult(resealed, unreadable)


async def _settled() -> None:
    return None


def _admin(
    store: MemoryEssayKeyStore | None = None,
) -> tuple[EssayKeyAdmin, MemoryEssayKeyStore, MemoryLedger, MemoryResealer]:
    store = store or MemoryEssayKeyStore()
    ledger = MemoryLedger()
    resealer = MemoryResealer(ledger)
    admin = EssayKeyAdmin(
        store,
        ledger,
        ScryptAesGcmBackupCodec(n=2**10),
        resealer,
        FakeTaskKicker(),
        FixedClock(),
        settle=_settled,
    )
    return admin, store, ledger, resealer


async def test_backup_round_trip_restores_into_an_empty_store() -> None:
    admin, store, ledger, _ = _admin()
    owners = [new_id(), new_id()]
    for owner in owners:
        await store.create(owner)
    file = await admin.backup(ADMIN, PASS)
    assert file.filename.startswith("essay-keys-g1-")
    doc = json.loads(file.content)
    assert doc["count"] == 2 and doc["kdf"]["name"] == "scrypt"
    for owner in owners:  # no plaintext key in the file
        key = store.keys[owner]
        assert key.secret not in file.content
        assert key.secret.hex().encode() not in file.content
    assert [e.action for e in ledger.events] == ["essay_keys.backup"]

    fresh, empty, _, _ = _admin()
    report = await fresh.restore(ADMIN, file.content, PASS)
    assert (report.restored, report.skipped, report.conflicts) == (2, 0, [])
    assert empty.keys == store.keys


async def test_backup_only_once_per_generation() -> None:
    admin, store, ledger, _ = _admin()
    await store.create(new_id())
    await admin.backup(ADMIN, PASS)
    with pytest.raises(EssayKeysBackupTakenError):
        await admin.backup(ADMIN, PASS)
    ledger.generation += 1  # after a rotation a new backup is allowed
    await admin.backup(ADMIN, PASS)


async def test_backup_needs_admin() -> None:
    admin, _, _, _ = _admin()
    teacher = Actor(user_id=new_id(), roles=frozenset({Role.TEACHER}))
    with pytest.raises(AdmissionForbiddenError):
        await admin.backup(teacher, PASS)


async def test_wrong_passphrase_or_damage_is_invalid() -> None:
    admin, store, _, _ = _admin()
    await store.create(new_id())
    file = await admin.backup(ADMIN, PASS)
    with pytest.raises(EssayKeysBackupInvalidError):
        await admin.restore(ADMIN, file.content, "wrong passphrase!!")
    doc = json.loads(file.content)
    doc["generation"] = 7  # bound into the associated data
    with pytest.raises(EssayKeysBackupInvalidError):
        await admin.restore(ADMIN, json.dumps(doc).encode(), PASS)
    with pytest.raises(EssayKeysBackupInvalidError):
        await admin.restore(ADMIN, b"not json", PASS)


async def test_restore_never_overwrites() -> None:
    admin, store, _, _ = _admin()
    same, other = new_id(), new_id()
    await store.create(same)
    await store.create(other)
    file = await admin.backup(ADMIN, PASS)
    original = store.keys[same]

    target = MemoryEssayKeyStore()
    target.keys[same] = original
    target.keys[other] = EssayKey(other, b"\x01" * 32)  # a different key
    restorer, _, _, _ = _admin(target)
    report = await restorer.restore(ADMIN, file.content, PASS)
    assert (report.restored, report.skipped, report.conflicts) == (0, 1, [other])
    assert target.keys[other].secret == b"\x01" * 32


async def test_rotation_reseals_everything_and_counts_unreadable() -> None:
    admin, store, ledger, resealer = _admin()
    cipher = AesGcmEssayCipher(store)
    owner = new_id()
    old = await store.create(owner)
    good, broken = new_id(), new_id()
    resealer.blobs[(owner, good, "body")] = seal_blob(
        old.secret, owner, good, "body", "my essay"
    )
    resealer.blobs[(owner, broken, "body")] = seal_blob(
        b"\x02" * 32, owner, broken, "body", "lost"
    )
    state = await admin.rotate(ADMIN)
    assert state.rotation.state == "running"
    run_id = state.rotation.run_id
    assert run_id is not None
    kicks = admin._kicker.calls  # type: ignore[attr-defined]
    assert kicks == [(ROTATE_TASK, {"run_id": str(run_id)})]
    with pytest.raises(EssayKeysRotationRunningError):
        await admin.rotate(ADMIN)

    await admin.run_rotation(run_id)
    new = store.keys[owner]
    assert new.pending is None and new.secret != old.secret
    blob = resealer.blobs[(owner, good, "body")]
    assert open_blob(new.secret, owner, good, "body", blob) == "my essay"
    assert open_blob(old.secret, owner, good, "body", blob) is None
    assert await cipher.open(owner, good, "body", blob) == "my essay"
    assert ledger.rotation.state == "done"
    assert (ledger.rotation.total, ledger.rotation.done) == (1, 1)
    assert ledger.rotation.unreadable == 1
    assert ledger.generation == 2

    await admin.run_rotation(run_id)  # not running any more: a no-op
    assert store.keys[owner] == new


async def test_fresh_run_blocks_a_second_start_stale_run_is_taken_over() -> None:
    admin, store, ledger, _ = _admin()
    await store.create(new_id())
    first = (await admin.rotate(ADMIN)).rotation.run_id
    clock: FixedClock = admin._clock  # type: ignore[assignment]
    clock.advance(minutes=9)
    with pytest.raises(EssayKeysRotationRunningError):
        await admin.rotate(ADMIN)
    clock.advance(seconds=STALE_AFTER.total_seconds())
    second = (await admin.rotate(ADMIN)).rotation.run_id
    assert second is not None and second != first
    assert first is not None
    await admin.run_rotation(first)  # fenced: the old run does nothing
    assert ledger.rotation.run_id == second and ledger.generation == 1
    await admin.run_rotation(second)
    assert ledger.rotation.state == "done" and ledger.generation == 2


async def test_wrong_run_id_is_fenced_and_never_promotes() -> None:
    admin, store, ledger, resealer = _admin()
    owner = new_id()
    old = await store.create(owner)
    run_id = (await admin.rotate(ADMIN)).rotation.run_id
    assert run_id is not None
    await store.begin_rotation(owner)
    with pytest.raises(RotationFencedError):
        await resealer.reseal(store.keys[owner], new_id())
    await admin.run_rotation(new_id())
    assert store.keys[owner].secret == old.secret
    assert ledger.rotation.state == "running" and ledger.generation == 1


async def test_promote_only_the_exact_pending_key() -> None:
    store = MemoryEssayKeyStore()
    owner = new_id()
    old = await store.create(owner)
    pending = await store.begin_rotation(owner)
    assert pending is not None and pending.pending is not None
    assert not await store.finish_rotation(owner, b"\x07" * 32)
    assert store.keys[owner].secret == old.secret
    assert await store.finish_rotation(owner, pending.pending)
    assert store.keys[owner].secret == pending.pending


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("kdf", "n"), 2**20),
        (("kdf", "r"), 16),
        (("kdf", "p"), 2),
        (("kdf", "length"), 64),
        (("kdf", "salt"), "AAAA"),
        (("cipher", "nonce"), "AAAA"),
        (("count",), 20_001),
    ],
)
async def test_restore_rejects_other_kdf_params_and_sizes(
    path: tuple[str, ...], value: object
) -> None:
    admin, store, _, _ = _admin()
    await store.create(new_id())
    doc = json.loads((await admin.backup(ADMIN, PASS)).content)
    target = doc
    for part in path[:-1]:
        target = target[part]
    target[path[-1]] = value
    with pytest.raises(EssayKeysBackupInvalidError):
        await admin.restore(ADMIN, json.dumps(doc).encode(), PASS)


@pytest.mark.parametrize("state", ["running", "failed"])
async def test_backup_refused_during_a_running_or_failed_rotation(state: str) -> None:
    admin, store, ledger, _ = _admin()
    await store.create(new_id())
    ledger.rotation = dataclasses.replace(
        ledger.rotation, state=state  # type: ignore[arg-type]
    )
    with pytest.raises(EssayKeysRotationRunningError):
        await admin.backup(ADMIN, PASS)
    assert ledger.exports == {}


async def test_open_refreshes_a_stale_cached_key_once() -> None:
    store = MemoryEssayKeyStore()
    cipher = AesGcmEssayCipher(store)
    owner, record = new_id(), new_id()
    await cipher.seal(owner, record, "body", "warm the cache")
    rotated = await store.begin_rotation(owner)
    assert rotated is not None and rotated.pending is not None
    blob = seal_blob(rotated.pending, owner, record, "body", "new text")
    assert await cipher.open(owner, record, "body", blob) == "new text"
