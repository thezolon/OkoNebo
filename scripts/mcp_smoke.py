#!/usr/bin/env python3
"""Import-and-register smoke test for the MCP adapter.

CI's py_compile step only parses scripts/mcp_server.py; it never imports it, so a
breaking `mcp` release (such as 1.x -> 2.x, which moved FastMCP to MCPServer) would
pass CI and fail only at runtime. This imports the adapter for real and asserts the
tool surface is intact.

Usage:
  python scripts/mcp_smoke.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import mcp_server  # noqa: E402

# Declaration order in mcp_server.py. Protocol revision 2026-07-28 asks servers to
# return tools/list in a deterministic order so clients can cache it, so this is
# compared exactly rather than as a set.
EXPECTED_TOOLS = [
    "get_capabilities",
    "get_config",
    "get_bootstrap",
    "get_current",
    "get_forecast",
    "get_hourly",
    "get_alerts",
    "get_metar",
    "get_tides",
    "get_pws",
    "get_pws_trend",
    "get_stats",
    "get_debug",
]


async def main() -> int:
    tools = await mcp_server.mcp.list_tools()
    names = [tool.name for tool in tools]

    missing = sorted(set(EXPECTED_TOOLS) - set(names))
    if missing:
        print(f"FAIL: tools missing from the MCP surface: {missing}")
        return 1

    unexpected = sorted(set(names) - set(EXPECTED_TOOLS))
    if unexpected:
        print(f"FAIL: undeclared tools registered (update EXPECTED_TOOLS): {unexpected}")
        return 1

    if names != EXPECTED_TOOLS:
        print("FAIL: tools/list order is not deterministic")
        print(f"  expected: {EXPECTED_TOOLS}")
        print(f"  actual:   {names}")
        return 1

    print(f"OK: {len(names)} MCP tools registered on {mcp_server.mcp.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
