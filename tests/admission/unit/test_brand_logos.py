"""University logos next to every returned institution name."""

from app.interfaces.http.v1.admission.routes_documents import (
    ChecklistOut,
    DeadlineOut,
    MilestoneOut,
)
from app.interfaces.http.v1.admission.routes_outcomes import OutcomeTallyOut
from app.modules.admission.domain.documents import ChecklistItem, Deadline, Milestone
from app.modules.admission.domain.errors import AdmissionForbiddenError
from app.modules.admission.domain.institution_brand import InstitutionBrand
from app.modules.admission.domain.outcomes import OutcomeTally
from app.shared.actor import Role
from app.shared.ids import new_id
from tests.admission.unit.fakes_documents import DocKit
from tests.admission.unit.test_documents_flow import _entry

import pytest

# A storage URL: the HTTP layer answers external logo URLs as null.
OWN = "http://localhost:9000/ihsp-dev/admission/org-media/c.png"
LOGO = InstitutionBrand("Columbia", OWN, "contain", 1.4)


async def test_checklist_carries_the_logo_of_per_university_items() -> None:
    """ADM-T2-1: a per-university item returns name, logo, fit and zoom."""
    k = DocKit()
    ctx = await k.w.ctx(k.student, Role.STUDENT)
    entry = _entry(k)
    k.d.institution_logos[entry.institution_id] = LOGO
    shared = ChecklistItem(new_id(), k.student, "shared.passport", "passport")
    per_uni = ChecklistItem(
        new_id(), k.student, "entry.essay", "essay", list_entry_id=entry.id
    )
    k.d.items[shared.id] = shared
    k.d.items[per_uni.id] = per_uni
    rows = {i.id: ChecklistOut.of(i, b) for i, b in await k.docs.checklist(ctx)}
    out = rows[per_uni.id]
    assert (out.institution_name, out.logo_url) == ("Columbia", LOGO.logo_url)
    assert (out.logo_fit, out.logo_zoom) == ("contain", 1.4)
    plain = rows[shared.id]
    assert plain.institution_name is None and plain.logo_url is None
    assert (plain.logo_fit, plain.logo_zoom) == ("circle", 1.0)


async def test_patch_checklist_returns_the_same_brand() -> None:
    """ADM-T2-2: the patched item carries the logo of its university."""
    k = DocKit()
    ctx = await k.w.ctx(k.student, Role.STUDENT)
    entry = _entry(k)
    k.d.institution_logos[entry.institution_id] = LOGO
    item = ChecklistItem(
        new_id(), k.student, "entry.essay", "essay", list_entry_id=entry.id
    )
    k.d.items[item.id] = item
    saved, brand = await k.docs.patch_checklist(ctx, item.id, important=True)
    out = ChecklistOut.of(saved, brand)
    assert out.logo_url == LOGO.logo_url and out.logo_zoom == 1.4


async def test_milestones_carry_the_logo() -> None:
    """ADM-T2-3: a student's milestone returns the logo; unknown logo is null."""
    k = DocKit()
    ctx = await k.w.ctx(k.student, Role.STUDENT)
    entry = _entry(k)
    k.d.institution_logos[entry.institution_id] = LOGO
    m = Milestone(new_id(), entry.id, "deadline")
    k.d.milestones[m.id] = m
    [item] = await k.deadlines.mine(ctx)
    out = MilestoneOut.of(item)
    assert (out.institution_name, out.logo_url) == ("Columbia", LOGO.logo_url)
    assert (out.logo_fit, out.logo_zoom) == ("contain", 1.4)


async def test_milestone_without_a_logo_uses_defaults() -> None:
    """ADM-T2-4: a university without a logo gives null url, circle, zoom 1."""
    k = DocKit()
    ctx = await k.w.ctx(k.student, Role.STUDENT)
    entry = _entry(k)
    m = Milestone(new_id(), entry.id, "deadline")
    k.d.milestones[m.id] = m
    [item] = await k.deadlines.mine(ctx)
    out = MilestoneOut.of(item)
    assert out.logo_url is None
    assert (out.logo_fit, out.logo_zoom) == ("circle", 1.0)


async def test_staff_brand_lookup_needs_the_manage_right() -> None:
    """ADM-T2-5: staff with the right get brands; a student is refused."""
    k = DocKit()
    inst = new_id()
    k.d.institution_logos[inst] = LOGO
    staff = await k.w.ctx(k.staff, Role.ADMIN)
    assert await k.deadlines.institution_brands(staff, {inst}) == {inst: LOGO}
    assert await k.deadlines.institution_brands(staff, set()) == {}
    student = await k.w.ctx(k.student, Role.STUDENT)
    with pytest.raises(AdmissionForbiddenError):
        await k.deadlines.institution_brands(student, {inst})


def test_deadline_out_maps_brand_and_defaults() -> None:
    """ADM-T2-6: the deadline view takes the brand, or an empty one."""
    d = Deadline(new_id(), new_id(), 2026, "RD")
    with_logo = DeadlineOut.of(d, LOGO)
    assert (with_logo.institution_name, with_logo.logo_fit) == ("Columbia", "contain")
    bare = DeadlineOut.of(d)
    assert (bare.institution_name, bare.logo_url, bare.logo_zoom) == ("", None, 1.0)


def test_outcome_tally_maps_brand_and_unknown_institution() -> None:
    """ADM-T2-7: the tally carries the logo; an unknown id gets defaults."""
    known, unknown = new_id(), new_id()
    brands = {known: LOGO}
    a = OutcomeTallyOut.of(OutcomeTally(known, 2026), brands)
    assert (a.institution_name, a.logo_url, a.logo_zoom) == (
        "Columbia",
        LOGO.logo_url,
        1.4,
    )
    b = OutcomeTallyOut.of(OutcomeTally(unknown, 2026), brands)
    assert (b.institution_name, b.logo_url, b.logo_fit) == ("", None, "circle")
