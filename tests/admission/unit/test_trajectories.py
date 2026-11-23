"""Educational trajectories: validation, cycles, curator gate and progress."""

from types import SimpleNamespace
from typing import Any
from uuid import UUID

from app.modules.admission.application.trajectories import TrajectoryService
from app.modules.admission.domain.errors import (
    AdmissionForbiddenError,
    AdmissionNotFoundError,
)
from app.modules.admission.domain.trajectories import (
    Edge,
    ResourceHit,
    Trajectory,
    check_acyclic,
    clean_trajectory,
)
from app.modules.admission.ports.trajectories import TrajectorySlugTakenError
from app.shared.base_error import ValidationFailedError

import pytest


def _node(nid: str, **over: Any) -> dict[str, Any]:
    return {
        "id": nid,
        "title": {"en": nid.title()},
        "kind": "topic",
        "level": "beginner",
        "description": {},
        "optional": False,
        "resources": [],
    } | over


def _values(**over: Any) -> dict[str, Any]:
    return {
        "slug": "computer-science",
        "field": "cs_it",
        "title": {"en": "CS"},
        "description": {},
        "published": True,
        "stages": [
            {"id": "base", "title": {"en": "Base"}, "nodes": [_node("a")]},
            {
                "id": "next",
                "title": {"en": "Next"},
                "nodes": [_node("b"), _node("c", optional=True)],
            },
        ],
        "edges": [{"before": "a", "after": "b"}, {"before": "a", "after": "c"}],
    } | over


def _reason(values: dict[str, Any]) -> dict[str, Any]:
    with pytest.raises(ValidationFailedError) as err:
        clean_trajectory(values)
    return dict(err.value.params or {})


def test_clean_trajectory_normalizes_and_dedupes_edges() -> None:
    edges = [{"before": "a", "after": "b"}] * 2
    cleaned = clean_trajectory(_values(slug="Computer-Science", edges=edges))
    assert cleaned["slug"] == "computer-science"
    assert cleaned["edges"] == (Edge("a", "b"),)
    assert [n.id for s in cleaned["stages"] for n in s.nodes] == ["a", "b", "c"]


@pytest.mark.parametrize(
    ("over", "field", "reason"),
    [
        ({"slug": "Not a slug"}, "slug", None),
        ({"field": "astrology"}, "field", None),
        ({"edges": [{"before": "a", "after": "zz"}]}, "edges", "unknown_node"),
        ({"edges": [{"before": "a", "after": "a"}]}, "edges", "cycle"),
        (
            {
                "edges": [
                    {"before": "a", "after": "b"},
                    {"before": "b", "after": "c"},
                    {"before": "c", "after": "a"},
                ]
            },
            "edges",
            "cycle",
        ),
    ],
)
def test_clean_trajectory_rejects(
    over: dict[str, Any], field: str, reason: str | None
) -> None:
    params = _reason(_values(**over))
    assert params["field"] == field
    if reason:
        assert params["reason"] == reason


def test_duplicate_nodes_and_bad_resources_are_rejected() -> None:
    dup = _values(
        stages=[{"id": "s", "title": {"en": "S"}, "nodes": [_node("a"), _node("a")]}],
        edges=[],
    )
    assert _reason(dup) == {"field": "nodes.id", "reason": "duplicate"}
    bad_url = _values(
        stages=[
            {
                "id": "s",
                "title": {"en": "S"},
                "nodes": [
                    _node(
                        "a", resources=[{"kind": "url", "ref": "ftp://x", "title": ""}]
                    )
                ],
            }
        ],
        edges=[],
    )
    assert _reason(bad_url)["reason"] == "url"


def test_check_acyclic_accepts_a_diamond() -> None:
    check_acyclic(
        "abcd",
        [Edge("a", "b"), Edge("a", "c"), Edge("b", "d"), Edge("c", "d")],
    )
    with pytest.raises(ValidationFailedError):
        check_acyclic("ab", [Edge("a", "b"), Edge("b", "a")])


class _Repo:
    def __init__(self) -> None:
        self.rows: dict[UUID, Trajectory] = {}
        self.marks: dict[tuple[UUID, UUID, str], str] = {}

    async def all(self, *, published_only: bool) -> list[Trajectory]:
        return [t for t in self.rows.values() if t.published or not published_only]

    async def get(self, tid: UUID) -> Trajectory | None:
        return self.rows.get(tid)

    async def get_by_slug(self, slug: str) -> Trajectory | None:
        return next((t for t in self.rows.values() if t.slug == slug), None)

    async def save(self, t: Trajectory) -> Trajectory:
        if any(o.slug == t.slug and o.id != t.id for o in self.rows.values()):
            raise TrajectorySlugTakenError()
        self.rows[t.id] = t
        return t

    async def delete(self, tid: UUID) -> bool:
        return self.rows.pop(tid, None) is not None

    async def progress(
        self, student_id: UUID, ids: list[UUID]
    ) -> dict[UUID, dict[str, str]]:
        out: dict[UUID, dict[str, str]] = {}
        for (sid, tid, nid), status in self.marks.items():
            if sid == student_id and tid in ids:
                out.setdefault(tid, {})[nid] = status
        return out

    async def set_progress(
        self, student_id: UUID, tid: UUID, nid: str, status: str | None
    ) -> None:
        if status is None:
            self.marks.pop((student_id, tid, nid), None)
        else:
            self.marks[(student_id, tid, nid)] = status


class _Resources:
    async def find(self, actor: Any, kind: str, query: Any, limit: int) -> list[Any]:
        return [ResourceHit(kind, "algo-101", "Algorithms", "LMS", "")]  # type: ignore


class _Uow:
    def __init__(self, log: list[str]) -> None:
        self.access = SimpleNamespace(audit=lambda e: log.append(e.action))

    async def __aenter__(self) -> "_Uow":
        return self

    async def __aexit__(self, *_: Any) -> None:
        return None

    async def commit(self) -> None:
        return None


def _ctx(applicant: bool) -> Any:
    return SimpleNamespace(
        user_id=UUID(int=7 if applicant else 9),
        actor=None,
        admission=SimpleNamespace(is_applicant=applicant),
    )


def _service(repo: _Repo, log: list[str], curator: bool) -> TrajectoryService:
    return TrajectoryService(
        repo,  # type: ignore[arg-type]
        _Resources(),  # type: ignore[arg-type]
        lambda: _Uow(log),  # type: ignore[arg-type, return-value]
        lambda _c: curator,
        "https://lms.example/",
        "https://lib.example",
    )


async def test_curators_edit_others_are_forbidden() -> None:
    repo, log = _Repo(), []
    staff, student = _ctx(False), _ctx(True)
    with pytest.raises(AdmissionForbiddenError):
        await _service(repo, log, False).create(student, _values())
    svc = _service(repo, log, True)
    made = await svc.create(staff, _values(published=False))
    with pytest.raises(ValidationFailedError):
        await svc.create(staff, _values())  # same slug
    await svc.update(staff, made.id, _values(slug="cs-2", published=False))
    hits = await svc.find_resources(staff, "lms_course", "algo")
    assert hits[0].url == "https://lms.example/course/algo-101/"
    # drafts stay hidden from students
    reader = _service(repo, log, False)
    assert await reader.browse(student, None, None) == []
    with pytest.raises(AdmissionNotFoundError):
        await reader.open(student, "cs-2")
    await svc.delete(staff, made.id)
    assert log == ["trajectory.created", "trajectory.edited", "trajectory.deleted"]


async def test_students_track_progress_on_published_trajectories() -> None:
    repo, log = _Repo(), []
    staff, student = _ctx(False), _ctx(True)
    made = await _service(repo, log, True).create(staff, _values())
    svc = _service(repo, log, False)
    view = await svc.mark(student, made.id, "a", "done")
    assert view.progress == {"a": "done"}
    with pytest.raises(AdmissionNotFoundError):
        await svc.mark(student, made.id, "nope", "done")
    [summary] = await svc.browse(student, "cs", "cs_it")
    assert (summary.required, summary.done) == (2, 1)
    assert await svc.browse(student, None, "medicine_bio") == []
    view = await svc.mark(student, made.id, "a", None)
    assert view.progress == {}
    # staff see no personal progress
    assert (await svc.open(staff, made.slug)).progress == {}
