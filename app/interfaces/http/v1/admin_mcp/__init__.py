"""Administration: the MCP call log of every user."""

from app.interfaces.http.v1.admin_mcp.router import router

from fastapi import APIRouter

ROUTERS: list[APIRouter] = [router]
