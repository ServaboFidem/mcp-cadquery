"""Cancellation: a long OCC call can be abandoned without corrupting the stream."""

from __future__ import annotations

import asyncio

import pytest


def test_cancelled_call_frees_the_caller_and_next_call_succeeds(server_context):
    import mcp_cadquery_server.handlers as h

    from cadquery_dxl_mcp.server import execute_tool

    h.SLEEP_ON_CALL["search_parts"] = 30.0

    async def scenario():
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(
                execute_tool(
                    server_context,
                    "search_parts",
                    {"query": "slow"},
                    request_id="slow-1",
                ),
                timeout=2.0,
            )
        # The stream is intact: the next call through the same context succeeds.
        ok = await execute_tool(
            server_context, "search_parts", {"query": "gear"}, request_id="fast-1"
        )
        assert not ok.is_error

    asyncio.run(scenario())
