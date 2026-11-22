"""Essay key administration: backup once, restore never overwrites, rotation."""

import datetime as dt
import json
from uuid import UUID

from app.modules.admission.application.essay_keys import ROTATE_TASK, EssayKeyAdmin
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
    EssayKeyLedgerState,
    ResealResult,
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
    """In-memory `EssayKeyLedger`."""

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

    async def claim_export(
        self, generation: int, actor_id: UUID, at: dt.datetime, event: AuditEvent
    ) -> bool:
        if generation in self.exports:
            return False
        self.exports[generation] = (at, actor_id)
        self.events.append(event)
        return True

    async def start_rotation(self, actor_id: UUID, at: dt.datetime) -> bool:
        if self.rotation.state == "running":
            return False
        self.rotation = RotationProgress("running", 0, 0, 0, at, None, actor_id)
        return True

    def _with(self, **kw: object) -> None:
        r = self.rotation
        values = {
            "state": r.state,
            "total": r.total,
            "done": r.done,
            "unreadable": r.unreadable,
            "started_at": r.started_at,
            "finished_at": r.finished_at,
            "requested_by": r.requested_by,
        }
        values.update(kw)
        self.rotation = RotationProgress(**values)  # type: ignore[arg-type]

    async def set_total(self, total: int) -> None:
        self._with(total=total, done=0, unreadable=0)

    async def advance(self, unreadable: int) -> None:
        r = self.rotation
        self._with(done=r.done + 1, unreadable=r.unreadable + unreadable)

    async def finish_rotation(self, at: dt.datetime) -> None:
        self._with(state="done", finished_at=at)
        self.generation += 1

    async def fail_rotation(self, at: dt.datetime) -> None:
        self._with(state="failed", finished_at=at)

    async def audit(self, event: AuditEvent) -> None:
        self.events.append(event)


class MemoryResealer:
    """Blobs per (owner, record, column), moved with the production `move_blob`."""

    def __init__(self) -> None:
        self.blobs: dict[tuple[UUID, UUID, str], bytes] = {}

    async def reseal(self, key: EssayKey) -> ResealResult:
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
    ledger, resealer = MemoryLedger(), MemoryResealer()
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
    assert admin._kicker.calls == [(ROTATE_TASK, {})]  # type: ignore[attr-defined]
    with pytest.raises(EssayKeysRotationRunningError):
        await admin.rotate(ADMIN)

    await admin.run_rotation()
    new = store.keys[owner]
    assert new.pending is None and new.secret != old.secret
    blob = resealer.blobs[(owner, good, "body")]
    assert open_blob(new.secret, owner, good, "body", blob) == "my essay"
    assert open_blob(old.secret, owner, good, "body", blob) is None
    assert (
        await cipher.open(owner, good, "body", blob)  # type: ignore[call-arg]
        == "my essay"
    )
    assert ledger.rotation.state == "done"
    assert (ledger.rotation.total, ledger.rotation.done) == (1, 1)
    assert ledger.rotation.unreadable == 1
    assert ledger.generation == 2

    await admin.run_rotation()  # not running any more: a no-op
    assert store.keys[owner] == new
