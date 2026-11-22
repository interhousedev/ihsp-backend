"""What a university says it looks for: the verified, on-site items only."""

from app.modules.admission.domain.chooser import CatalogInstitution
from app.modules.admission.domain.focuses import served_focuses

from pydantic import BaseModel, Field


class FocusOut(BaseModel):
    """One verified focus: a paraphrase, the university's own sentence and its page."""

    text: str = Field(description="Short paraphrase in the request language.")
    quote: str = Field(description="The exact English sentence on the page.")
    source_url: str = Field(description="The page, on the university's own site.")


def focuses_out(i: CatalogInstitution, locale: str = "en") -> list[FocusOut]:
    """Verified focuses of the institution; empty when it has none."""
    fact = i.fact("focuses")
    if fact is None:
        return []
    return [
        FocusOut(
            text=x["text"].get(locale) or x["text"]["en"],
            quote=x["quote"],
            source_url=x["source_url"],
        )
        for x in served_focuses(fact.value, i.website_domain)
    ]
