#!/usr/bin/env python3
"""OkoNebo MCP adapter.

Exposes OkoNebo weather endpoints as MCP tools for AI agent runtimes.

Usage:
  export OKONEBO_BASE_URL=http://localhost:8888
  export OKONEBO_AGENT_TOKEN=<agent bearer token>
  python scripts/mcp_server.py
"""

from __future__ import annotations

import os
from typing import Any

import httpx

try:
    from mcp.server.fastmcp import FastMCP
except Exception as exc:  # pragma: no cover - optional runtime
    raise SystemExit(
        "Missing MCP runtime. Install extras with: pip install -r requirements-mcp.txt"
    ) from exc

BASE_URL = os.getenv("OKONEBO_BASE_URL", "http://localhost:8888").rstrip("/")
AGENT_TOKEN = os.getenv("OKONEBO_AGENT_TOKEN", "").strip()

mcp = FastMCP("okonebo-weather")


def _headers() -> dict[str, str]:
    headers: dict[str, str] = {}
    if AGENT_TOKEN:
        headers["Authorization"] = f"Bearer {AGENT_TOKEN}"
    return headers


async def _get(path: str, params: dict[str, Any] | None = None) -> Any:
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.get(f"{BASE_URL}{path}", headers=_headers(), params=params)
        resp.raise_for_status()
        return resp.json()


@mcp.tool()
async def get_capabilities() -> Any:
    return await _get("/api/capabilities")


@mcp.tool()
async def get_config() -> Any:
    return await _get("/api/config")


@mcp.tool()
async def get_bootstrap() -> Any:
    return await _get("/api/bootstrap")


@mcp.tool()
async def get_current() -> Any:
    return await _get("/api/current")


@mcp.tool()
async def get_forecast() -> Any:
    return await _get("/api/forecast")


@mcp.tool()
async def get_hourly() -> Any:
    return await _get("/api/hourly")


@mcp.tool()
async def get_alerts() -> Any:
    return await _get("/api/alerts")


@mcp.tool()
async def get_metar() -> Any:
    return await _get("/api/metar")


@mcp.tool()
async def get_tides(days: int = 2) -> Any:
    return await _get("/api/tides", {"days": max(1, min(int(days), 7))})


@mcp.tool()
async def get_pws() -> Any:
    return await _get("/api/pws")


@mcp.tool()
async def get_pws_trend(hours: int = 3) -> Any:
    return await _get("/api/pws/trend", {"hours": max(1, min(int(hours), 24))})


@mcp.tool()
async def get_stats() -> Any:
    return await _get("/api/stats")


@mcp.tool()
async def get_debug() -> Any:
    return await _get("/api/debug")


if __name__ == "__main__":
    mcp.run()
