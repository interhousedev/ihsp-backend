"""PATCH /v1/id/me/preferences: change some settings."""

from app.interfaces.http.v1.id.account.schemas import PreferencesPatchBody
from app.interfaces.http.v1.id.dependencies import ActorDep, AuthDep
from app.shared.contracts.identity import UserPreferences


async def patch_preferences(
    body: PreferencesPatchBody, actor: ActorDep, auth: AuthDep
) -> UserPreferences:
    """Merge the sent fields (an explicit null clears a nullable setting)."""
    patch = body.model_dump(exclude_unset=True, mode="json")
    return await auth.update_preferences.execute(actor, patch)
