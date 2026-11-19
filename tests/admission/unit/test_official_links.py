"""Official links: the university's own website on catalog and checklist items."""

from uuid import UUID

from app.interfaces.http.v1.admission.routes_chooser import InstitutionOut
from app.interfaces.http.v1.admission.routes_documents import ChecklistOut
from app.modules.admission.domain.chooser import CatalogInstitution
from app.modules.admission.domain.documents import ChecklistItem
from app.modules.admission.domain.institution_brand import InstitutionBrand

INSTITUTION = UUID("00000000-0000-0000-0000-0000000000d1")
STUDENT = UUID("00000000-0000-0000-0000-0000000000d2")


def _institution(domain: str | None) -> CatalogInstitution:
    return CatalogInstitution(
        id=INSTITUTION,
        slug=None,
        name="Example University",
        country="GB",
        city=None,
        status="published",
        website_domain=domain,
    )


def test_institution_out_carries_the_https_website() -> None:
    """ADM-LINKS-1: the catalog shows the university's own site as an https URL."""
    out = InstitutionOut.of(_institution("uni.example.edu"), "en")
    assert out.website_url == "https://uni.example.edu"
    assert InstitutionOut.of(_institution(None), "en").website_url is None


def test_checklist_item_carries_the_institution_website() -> None:
    """ADM-LINKS-1: a per-university checklist item links to the institution's site."""
    item = ChecklistItem(
        id=INSTITUTION,
        student_id=STUDENT,
        template_key="transcript",
        title_key="admission.checklist.transcript",
        list_entry_id=INSTITUTION,
    )
    brand = InstitutionBrand(
        name="Example University", website_url="https://uni.example.edu"
    )
    with_brand = ChecklistOut.of(item, brand)
    assert with_brand.institution_website_url == "https://uni.example.edu"
    assert with_brand.institution_name == "Example University"
    assert ChecklistOut.of(item).institution_website_url is None
