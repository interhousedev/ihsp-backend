"""Route dependency that answers 404 while a feature flag is off."""

from collections.abc import Awaitable, Callable
from typing import Annotated

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_container
from app.modules.notebooks.domain.errors import FeatureDisabledError
from app.shared.features import Feature, is_enabled

from fastapi import Depends


def require_feature(feature: Feature) -> Callable[..., Awaitable[None]]:
    """Return a dependency raising `FeatureDisabledError` (404) when disabled."""

    async def gate(container: Annotated[Container, Depends(get_container)]) -> None:
        if not is_enabled(container.settings, feature):
            raise FeatureDisabledError(params={"feature": feature.value})

    return gate
