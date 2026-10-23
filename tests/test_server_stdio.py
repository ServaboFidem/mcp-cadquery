"""Stock-client stdio round trip: initialize + list + call against the built shim."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from cadquery_dxl_mcp.server import ABSENT_TOOLS, ALLOWLIST
from cadquery_dxl_mcp.upstream import UPSTREAM_SRC_ENV

TESTS_DIR = Path(__file__).resolve().parent
SRC_DIR = TESTS_DIR.parent / "src"
FAKE_UPSTREAM = TESTS_DIR / "fixtures" / "fake_upstream"


def _server_params(workspace: Path) -> StdioServerParameters:
    env = dict(os.environ)
    # NOTE: production spawns `python -I -m cadquery_dxl_mcp serve ...` against
    # the installed venv; the test env has no installed package, so PYTHONPATH
    # carries the sources and -I is dropped (it would ignore PYTHONPATH).
    # Same serve code path either way; the exact prod argv is pinned in test_main.
    # The hatch env var points the child at the fake upstream through the
    # documented seam (same as the in-process loaded_upstream fixture): without
    # it, PYTHONPATH order alone decides, and in a checkout where the real
    # upstream sits beside the shim (src/mcp_cadquery_server) the real package
    # shadows the fake and the child fails to import.
    env["PYTHONPATH"] = os.pathsep.join([str(SRC_DIR), str(FAKE_UPSTREAM)])
    env[UPSTREAM_SRC_ENV] = str(FAKE_UPSTREAM)
    env["PYTHONUTF8"] = "1"
    return StdioServerParameters(
        command=sys.executable,
        args=[
            "-u",
            "-m",
            "cadquery_dxl_mcp",
            "serve",
            "--workspace-dir",
            str(workspace),
        ],
        env=env,
    )


def test_stdio_initialize_list_call_round_trip(tmp_path: Path):
    workspace = tmp_path / "ws"
    (workspace / "exports").mkdir(parents=True)

    async def scenario():
        async with stdio_client(_server_params(workspace)) as (read, write):
            async with ClientSession(read, write) as session:
                init = await session.initialize()
                assert init.server_info.name == "cadquery-dxl-mcp"

                listed = await session.list_tools()
                names = sorted(t.name for t in listed.tools)
                assert names == sorted(ALLOWLIST)
                for absent in ABSENT_TOOLS:
                    assert absent not in names

                found = await session.call_tool("search_parts", {"query": "gear"})
                assert not found.is_error
                payload = json.loads(found.content[0].text)
                assert payload == {"success": True, "matches": []}

                # An excluded tool is unknown to the server: an isError-shaped
                # refusal (v2 answers unknown tools inline), never a crash.
                unknown = await session.call_tool("launch_cq_editor", {})
                assert unknown.is_error
                assert "Unknown tool" in unknown.content[0].text

                # Jail rejection is isError, and the server keeps serving after it.
                bad = await session.call_tool(
                    "save_workspace_module",
                    {
                        "workspace_path": str(workspace),
                        "module_filename": "../evil.py",
                        "module_content": "x=1",
                    },
                )
                assert bad.is_error
                still_ok = await session.call_tool("search_parts", {"query": "gear"})
                assert not still_ok.is_error

    asyncio.run(scenario())
