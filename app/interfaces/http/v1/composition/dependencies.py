"""FastAPI dependency that gives handlers the composition use cases."""

from app.interfaces.http.v1.composition.services import Composition

from fastapi import Request


def get_composition(request: Request) -> Composition:
    """Return the composition installed on the app (see `install_composition`)."""
    composition: Composition | None = getattr(request.app.state, "composition", None)
    if composition is None:
        raise RuntimeError("composition endpoints are not wired: install_composition")
    return composition
