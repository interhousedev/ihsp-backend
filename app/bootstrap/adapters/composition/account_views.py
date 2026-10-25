"""AccountViews over the identity module's `GetUserDetail`."""

from uuid import UUID

from app.interfaces.http.v1.admin_users.schemas import AdminUserDetailResponse
from app.interfaces.http.v1.composition.ports import JsonObject
from app.modules.identity.application.get_user_detail import GetUserDetail
from app.modules.identity.application.request_context import RequestContext
from app.shared.actor import Actor


class AccountViewsAdapter:
    """Composition <- identity: the account of a user for administrators."""

    def __init__(self, get_user_detail: GetUserDetail) -> None:
        """Keep the identity use case."""
        self._get_user_detail = get_user_detail

    async def account(
        self, actor: Actor, user_id: UUID, *, ip: str | None, user_agent: str | None
    ) -> JsonObject:
        """Return `AdminUserDetail`.

        `GetUserDetail` records the audit event `student.viewed` for a student's
        account, so nothing is audited here.
        """
        context = RequestContext(ip=ip, user_agent=user_agent)
        detail = await self._get_user_detail.execute(actor, user_id, context)
        return AdminUserDetailResponse.detail(detail).model_dump(mode="json")
