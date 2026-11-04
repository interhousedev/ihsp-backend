"""Routes of MCP connectors and the scope catalog."""

from app.interfaces.http.v1.id.connectors.handlers.delete_connector import (
    delete_connector,
)
from app.interfaces.http.v1.id.connectors.handlers.get_connectors import get_connectors
from app.interfaces.http.v1.id.connectors.handlers.get_mcp_scopes import get_mcp_scopes
from app.interfaces.http.v1.id.connectors.handlers.post_connector import post_connector
from app.interfaces.http.v1.id.connectors.mcp_setup import (
    McpClientResponse,
    McpSetupResponse,
    NewMcpClientResponse,
    ProvisionedMcpSetupResponse,
    delete_mcp_client,
    get_mcp_clients,
    get_mcp_setup,
    post_mcp_client,
    provision_mcp_setup,
)
from app.interfaces.http.v1.id.connectors.schemas import (
    ConnectorResponse,
    NewConnectorResponse,
    ScopeCatalogResponse,
)

from fastapi import APIRouter, Response

router = APIRouter(prefix="/v1/id", tags=["id-connectors"])

router.add_api_route(
    "/me/connectors",
    get_connectors,
    methods=["GET"],
    response_model=list[ConnectorResponse],
)
router.add_api_route(
    "/me/connectors",
    post_connector,
    methods=["POST"],
    status_code=201,
    response_model=NewConnectorResponse,
)
router.add_api_route(
    "/me/connectors/{id}",
    delete_connector,
    methods=["DELETE"],
    status_code=204,
    response_class=Response,
)
router.add_api_route(
    "/mcp-scopes",
    get_mcp_scopes,
    methods=["GET"],
    response_model=ScopeCatalogResponse,
)
router.add_api_route(
    "/me/mcp-setup/{service}",
    get_mcp_setup,
    methods=["GET"],
    response_model=McpSetupResponse,
)
router.add_api_route(
    "/me/mcp-setup/{service}",
    provision_mcp_setup,
    methods=["POST"],
    response_model=ProvisionedMcpSetupResponse,
)
router.add_api_route(
    "/me/mcp-clients",
    get_mcp_clients,
    methods=["GET"],
    response_model=list[McpClientResponse],
)
router.add_api_route(
    "/me/mcp-clients",
    post_mcp_client,
    methods=["POST"],
    status_code=201,
    response_model=NewMcpClientResponse,
)
router.add_api_route(
    "/me/mcp-clients/{client_id}",
    delete_mcp_client,
    methods=["DELETE"],
    status_code=204,
    response_class=Response,
)
