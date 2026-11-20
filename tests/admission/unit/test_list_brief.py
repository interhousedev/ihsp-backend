"""List brief: candidate roles come from data, the model only writes text."""

from types import SimpleNamespace
from typing import Any

from app.modules.admission.application.list_plan import ListPlanService
from app.modules.admission.domain.budget import admit_rate_of
from app.modules.admission.domain.chooser import CatalogInstitution, FactView
from app.modules.admission.domain.classification import _rate_of, balance
from app.modules.admission.domain.list_brief import brief_candidates, needed_role
from app.modules.admission.infrastructure.ai.prompt_source import BuiltinPrompts
from app.modules.admission.ports.consent import AI
from app.shared.ids import new_id
from tests.admission.unit.fakes import NOW, FakeConsents
from tests.admission.unit.test_student_grounding import STUDENT, _aw
from tests.fakes.clock import FixedClock


def _inst(
    name: str, rate: float | None, verified: bool = True, intl: float | None = None
) -> CatalogInstitution:
    facts: dict[str, FactView] = {}
    if rate is not None:
        facts["acceptance_rate"] = FactView(
            {"min": rate, "max": rate}, "https://x.edu", 2026
        )
    if intl is not None:
        facts["intl_acceptance_rate"] = FactView(intl, "https://x.edu/i", 2026)
    return CatalogInstitution(
        new_id(),
        name.lower(),
        name,
        "US",
        None,
        "published" if verified else "provisional",
        facts,
    )


def test_rate_of_reads_the_international_rate_first() -> None:
    assert _rate_of(_inst("A", 10, intl=40)) == 40
    assert _rate_of(_inst("B", 10)) == 10


def test_admit_rate_prefers_international_and_labels_scope() -> None:
    both = _inst("A", 10, intl=4.5)
    r = admit_rate_of(both.fact("intl_acceptance_rate"), both.fact("acceptance_rate"))
    assert r is not None
    assert (r.percent, r.scope, r.year) == (4.5, "intl", 2026)
    only = _inst("B", 20)
    r2 = admit_rate_of(only.fact("intl_acceptance_rate"), only.fact("acceptance_rate"))
    assert (r2.percent, r2.scope) == (20.0, "overall")  # type: ignore[union-attr]
    assert admit_rate_of(None, None) is None


def test_candidates_skip_listed_unverified_and_reach_and_put_needed_role_first() -> (
    None
):
    safe, tgt = _inst("Safe U", 80), _inst("Target U", 35)
    reach, raw, listed = (
        _inst("Reach U", 4),
        _inst("Raw U", 80, False),
        _inst("Own U", 80),
    )
    bal = balance(["reach"] * 4)
    assert needed_role(bal) == "safety"
    got = brief_candidates(
        [tgt, safe, reach, raw, listed], {listed.id}, bal, None, 2026
    )
    assert [c.institution.name for c in got][0] == "Safe U"
    assert {c.institution.name for c in got} <= {"Safe U", "Target U"}
    assert got[0].role in ("safety", "target") and got[0].admit_rate is not None


def test_candidates_fall_back_to_unrated_institutions_when_no_rate_fits() -> None:
    """Only elite rates published: the catalog still yields suggestions."""
    elite = [_inst(f"Elite {n}", 4) for n in range(3)]
    plain = [_inst("Plain A", None), _inst("Plain B", None)]
    bal = balance(["reach", "reach", None, None, None, None])
    got = brief_candidates([*elite, *plain], set(), bal, None, 2026)
    assert {c.institution.name for c in got} == {"Plain A", "Plain B"}
    assert all(c.role == needed_role(bal) and c.admit_rate is None for c in got)


async def test_brief_keeps_only_listed_candidates_and_never_trusts_roles() -> None:
    safe = _inst("Safe U", 80)

    class Uow:
        catalog = SimpleNamespace(institutions=lambda: _aw([safe]))
        profiles = SimpleNamespace(get=lambda _s: _aw(None))

        async def __aenter__(self) -> "Uow":
            return self

        async def __aexit__(self, *exc: object) -> None:
            return None

    class Lists:
        async def view(self, ctx: Any, student_id: Any) -> list[Any]:
            return []

    class Access:
        async def resolve(self, ctx: Any, student_id: Any) -> Any:
            return SimpleNamespace(owner=True, permissions=frozenset())

    class Hits:
        async def hit(self, *a: Any, **k: Any) -> None:
            self.n = getattr(self, "n", 0) + 1

    class Ai:
        calls: list[dict[str, Any]] = []

        async def json(self, **kw: Any) -> tuple[dict[str, Any], str]:
            self.calls.append(kw)
            return {
                "headline": "H" * 200,
                "diagnosis": "D",
                "suggestions": [
                    {"candidate": 1, "reason": "ok", "role": "reach"},
                    {"candidate": 1, "reason": "dup"},
                    {"candidate": 9, "reason": "invented"},
                ],
                "next_steps": ["a", "", "b", "c", "d"],
            }, "m"

    async def quota(_: Any) -> int:
        return 5

    ai, hits = Ai(), Hits()
    ai.calls = []
    svc = ListPlanService(
        Uow,
        Access(),
        Lists(),
        ai,
        FakeConsents({STUDENT: frozenset({AI})}),  # type: ignore[arg-type]
        FixedClock(NOW),
        hits,
        quota,
        BuiltinPrompts(),  # type: ignore[arg-type]
    )
    ctx: Any = SimpleNamespace(user_id=STUDENT)
    b = await svc.brief(ctx, "en")
    assert len(b.headline) == 90 and hits.n == 1
    assert [s.candidate.institution.name for s in b.suggestions] == ["Safe U"]
    assert b.suggestions[0].candidate.role in ("safety", "target")
    assert b.next_steps == ["a", "b", "c"]
    assert "[candidate:1] Safe U" in str(ai.calls[0]["user"])
