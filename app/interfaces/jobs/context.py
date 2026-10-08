"""The container that task functions use, set once at worker startup."""

from app.bootstrap.container import Container

_container: Container | None = None


def set_container(container: Container) -> None:
    """Remember the worker's container (called by bootstrap/worker.py)."""
    global _container
    _container = container


def get_container() -> Container:
    """Return the worker's container."""
    if _container is None:
        raise RuntimeError("worker container is not initialised")
    return _container
