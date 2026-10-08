"""Connects the composition endpoints (alerts, search, iCal, admin dashboard)."""

from app.bootstrap.adapters.composition import build_composition_ports
from app.bootstrap.container import Container
from app.interfaces.http.v1.composition.wiring import (
    composition_from_container,
    install_composition,
)

from fastapi import FastAPI


def install_composition_for(app: FastAPI, container: Container) -> None:
    """Build the composition over the container's modules and attach it to the app."""
    composition = composition_from_container(
        container, build_composition_ports(container)
    )
    install_composition(app, composition)
