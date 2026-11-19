"""Exemplar ranking for the essay review."""

from uuid import UUID

from app.modules.admission.application.exemplar_search import UowExemplarSource
from app.modules.admission.domain.exemplars import Exemplar
from app.shared.ids import new_id
from tests.admission.unit.fakes import NOW
from tests.admission.unit.fakes_exemplars import FakeExemplarStore, FakeExemplarUow
from tests.fakes.clock import FixedClock


def _ex(
    kind: str, body: str, *, inst: UUID | None = None, status: str = "published"
) -> Exemplar:
    return Exemplar(
        id=new_id(), institution_id=inst, school_name="", year=2025,
        kind=kind, prompt="", title=body[:20], body=body, word_count=len(body.split()),
        source_url="https://e.com/" + new_id().hex, source_name="", tags=(),
        notes="", status=status, language="en", created_by=None, updated_by=None,
        created_at=NOW, updated_at=NOW, lock_version=0,
    )  # fmt: skip


async def _source(*items: Exemplar) -> UowExemplarSource:
    store = FakeExemplarStore()
    store.exemplars.update({e.id: e for e in items})
    return UowExemplarSource(lambda: FakeExemplarUow(store), FixedClock(NOW))


async def test_empty_library_gives_nothing() -> None:
    """ADM-EXM-9: no exemplars means no matches."""
    src = await _source()
    got = await src.closest(
        kind="personal_statement", prompt="", body="hi", institution_id=None
    )
    assert got == ()


async def test_drafts_never_match_and_kind_ranks_first() -> None:
    """ADM-EXM-9: only published ones match; the same kind beats a closer text."""
    text = "I grew up near the sea and learned to repair boats with my father"
    same = _ex("personal_statement", "I love chess and long walks in the city")
    other = _ex("supplement", text)
    draft = _ex("personal_statement", text, status="draft")
    src = await _source(same, other, draft)
    got = await src.closest(
        kind="personal_statement", prompt="", body=text, institution_id=None, k=3
    )
    assert [m.exemplar.id for m in got] == [same.id]


async def test_institution_boost_breaks_ties() -> None:
    """ADM-EXM-9: the same institution ranks above an equal text elsewhere."""
    inst = new_id()
    text = "robots and small engines shaped my curiosity about physics"
    a = _ex("supplement", text)
    b = _ex("supplement", text, inst=inst)
    src = await _source(a, b)
    got = await src.closest(
        kind="supplemental", prompt="", body=text, institution_id=inst, k=2
    )
    assert got[0].exemplar.id == b.id
