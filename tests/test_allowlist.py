"""Allowlist: exactly the 8 spec tools are registered; the 2 excluded are absent."""

from __future__ import annotations

import pytest

from cadquery_dxl_mcp.server import ABSENT_TOOLS, ALLOWLIST, build_server


def test_allowlist_has_exactly_eight_tools_in_spec_order():
    assert ALLOWLIST == (
        "execute_cadquery_script",
        "export_shape",
        "export_shape_to_svg",
        "scan_part_library",
        "search_parts",
        "save_workspace_module",
        "get_shape_properties",
        "get_shape_description",
    )


def test_absent_tools_are_the_two_exclusions():
    assert set(ABSENT_TOOLS) == {"launch_cq_editor", "install_workspace_package"}


async def _tool_names(server):
    listed = await server.list_tools()
    return sorted(t.name for t in listed)


def test_registered_tools_are_exactly_allowlist(server_context):
    import asyncio

    server = build_server(server_context)
    names = asyncio.run(_tool_names(server))
    assert names == sorted(ALLOWLIST)
    for absent in ABSENT_TOOLS:
        assert absent not in names


@pytest.mark.parametrize("tool_name", ALLOWLIST)
def test_each_allowlisted_tool_dispatches_to_upstream(server_context, tool_name):
    """Every exposed tool reaches the upstream seam and returns its result."""
    import asyncio

    from cadquery_dxl_mcp.server import execute_tool

    args: dict = {}
    if tool_name == "execute_cadquery_script":
        args = {"script": "result = cq.Workplane('XY').box(1, 1, 1)"}
    elif tool_name in ("export_shape", "export_shape_to_svg"):
        args = {"result_id": "r_0", "filename": "part.step"}
    elif tool_name == "save_workspace_module":
        args = {"module_filename": "gear.py", "module_content": "x = 1"}
    elif tool_name in ("get_shape_properties", "get_shape_description"):
        args = {"result_id": "r_0"}

    result = asyncio.run(execute_tool(server_context, tool_name, args, request_id="t1"))
    assert result.is_error in (False, None)


def test_calling_absent_tool_is_iserror_not_transport(server_context):
    """An unregistered name fails as a tool error, never a transport error."""
    import asyncio

    from cadquery_dxl_mcp.server import execute_tool

    for absent in ABSENT_TOOLS:
        result = asyncio.run(execute_tool(server_context, absent, {}, request_id="t1"))
        assert result.is_error is True
