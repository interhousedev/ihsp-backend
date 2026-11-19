"""How a university is shown beside its name: the name and its logo."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class InstitutionBrand:
    """A university's name and how its logo is drawn (as in the catalog).

    `logo_fit` is `circle` or `contain`, already resolved from the aspect ratio.
    """

    name: str
    logo_url: str | None = None
    logo_fit: str = "circle"
    logo_zoom: float = 1.0
