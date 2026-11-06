"""Router of the MCP permission buttons (before the guest router)."""

from app.interfaces.bot.routers.common.mcp_scopes.handlers import decide
from app.shared.contracts.callbacks import McpScopeCb

from aiogram import Router


def build_router() -> Router:
    """Build the router of the offer's buttons."""
    router = Router(name="common.mcp_scopes")
    router.callback_query.register(decide, McpScopeCb.filter())
    return router
