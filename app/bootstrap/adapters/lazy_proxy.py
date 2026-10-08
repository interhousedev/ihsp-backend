"""A stand-in for an object that is built later (breaks module cycles)."""

from typing import Any, Generic, TypeVar, cast

T = TypeVar("T")


class LazyProxy(Generic[T]):
    """Forwards attribute access to a target that is bound after construction.

    Modules that depend on each other (links and flash cards, links and AI) receive
    ``proxy.view`` while they are built; the composition root calls ``bind`` once
    the real object exists. Using the proxy before that raises ``RuntimeError``.
    """

    def __init__(self, name: str) -> None:
        """Create an unbound proxy; ``name`` appears in the error message."""
        self._name = name
        self._target: T | None = None

    def bind(self, target: T) -> None:
        """Set the real object (call once, during assembly)."""
        self._target = target

    @property
    def is_bound(self) -> bool:
        """True after ``bind``."""
        return self._target is not None

    @property
    def view(self) -> T:
        """The proxy typed as the target (for passing to ``build`` functions)."""
        return cast(T, self)

    def __getattr__(self, attribute: str) -> Any:  # noqa: ANN401 - forwards anything
        """Return the attribute of the bound target."""
        target = self.__dict__.get("_target")
        if target is None:
            raise RuntimeError(f"{self.__dict__.get('_name', '?')} is not bound yet")
        return getattr(target, attribute)
