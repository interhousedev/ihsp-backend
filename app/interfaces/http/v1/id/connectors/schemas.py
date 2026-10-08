"""Schemas of the MCP connector endpoints."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from app.modules.identity.application.get_mcp_scopes import ServerCatalog
from app.modules.identity.domain.connector import McpConnector
from app.shared.actor import Role

from pydantic import BaseModel, Field

Server = Literal["student", "lms", "admin"]


class ConnectorResponse(BaseModel):
    """Connector."""

    id: UUID
    name: str
    server: Server
    scopes: list[str]
    course_ids: list[UUID] | None
    kind: Literal["token", "oauth"]
    token_prefix: str | None
    created_at: datetime | None
    last_used_at: datetime | None
    expires_at: datetime | None
    revoked_at: datetime | None

    @classmethod
    def of(cls, connector: McpConnector) -> "ConnectorResponse":
        """Map a connector."""
        return cls(
            id=connector.id,
            name=connector.name,
            server=connector.server,
            scopes=connector.scopes,
            course_ids=connector.course_ids,
            kind=connector.kind,
            token_prefix=connector.token_prefix,
            created_at=connector.created_at,
            last_used_at=connector.last_used_at,
            expires_at=connector.expires_at,
            revoked_at=connector.revoked_at,
        )


class CreateConnectorBody(BaseModel):
    """POST /v1/id/me/connectors."""

    server: Server
    name: str = Field(min_length=1, max_length=80)
    scopes: list[str] = Field(min_length=1)
    course_ids: list[UUID] | None = None
    expires_in_days: int
    otp_code: str | None = Field(default=None, max_length=16)


class NewConnectorResponse(BaseModel):
    """The connector and its token, shown once."""

    connector: ConnectorResponse
    token: str


class ScopeResponse(BaseModel):
    """One scope and its tools."""

    scope: str
    tools: list[str]


class PresetResponse(BaseModel):
    """A named set of scopes."""

    key: str
    scopes: list[str]


class ServerCatalogResponse(BaseModel):
    """One server of the scope catalog."""

    server: Server
    roles: list[Role]
    scopes: list[ScopeResponse]
    presets: list[PresetResponse]

    @classmethod
    def of(cls, catalog: ServerCatalog) -> "ServerCatalogResponse":
        """Map a catalog entry."""
        return cls(
            server=catalog.server,
            roles=catalog.roles,
            scopes=[
                ScopeResponse(scope=s.scope, tools=list(s.tools))
                for s in catalog.scopes
            ],
            presets=[
                PresetResponse(key=p.key, scopes=list(p.scopes))
                for p in catalog.presets
            ],
        )


class ScopeCatalogResponse(BaseModel):
    """ScopeCatalog."""

    servers: list[ServerCatalogResponse]
