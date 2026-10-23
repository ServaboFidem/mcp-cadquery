"""Workspace jail: every server-side path stays under the root."""

from __future__ import annotations

import pytest

from cadquery_dxl_mcp import errors, workspace


def test_workspace_path_defaults_to_root(server_context):
    assert (
        workspace.resolve_call_workspace(server_context.workspace_root, None)
        == server_context.workspace_root
    )


def test_workspace_path_equal_to_root_allowed(server_context):
    root = server_context.workspace_root
    assert workspace.resolve_call_workspace(root, str(root)) == root


def test_workspace_path_subdir_allowed(server_context):
    root = server_context.workspace_root
    sub = root / "parts"
    sub.mkdir()
    assert workspace.resolve_call_workspace(root, str(sub)) == sub


@pytest.mark.parametrize(
    "evil",
    [
        "..",
        "../outside",
        "sub/../../outside",
        "/abs/posix",
        r"C:\Windows\Temp",
        r"\\server\share",
        r"\leading\backslash",
        "C:/Windows/Temp",
    ],
)
def test_workspace_path_escapes_rejected(server_context, evil):
    with pytest.raises(errors.WorkspaceEscapeError):
        workspace.resolve_call_workspace(server_context.workspace_root, evil)


def test_module_filename_ok(server_context):
    assert workspace.check_module_filename("gear.py") == "gear.py"


@pytest.mark.parametrize(
    "evil",
    [
        "",
        ".",
        "..",
        "gear.txt",
        "gear",
        "sub/gear.py",
        r"sub\gear.py",
        "/abs/gear.py",
        "a.py/.",
    ],
)
def test_module_filename_rejected(evil):
    with pytest.raises(errors.InvalidFilenameError):
        workspace.check_module_filename(evil)


@pytest.mark.parametrize("evil", ["os.py", "sys.py", "cadquery.py", "OS.PY", "Sys.Py"])
def test_module_filename_reserved_names_rejected(evil):
    """Planted stdlib/top-package names would shadow future imports (V2)."""
    with pytest.raises(errors.InvalidFilenameError):
        workspace.check_module_filename(evil)


def test_export_filename_ok():
    assert workspace.check_export_filename("part.step") == "part.step"


@pytest.mark.parametrize(
    "evil",
    ["", "sub/part.step", r"sub\part.step", "../part.step", "/abs.step", "C:\\x.step"],
)
def test_export_filename_rejected(evil):
    with pytest.raises(errors.InvalidFilenameError):
        workspace.check_export_filename(evil)


def test_stl_format_rejected_naming_step():
    with pytest.raises(errors.UnsupportedFormatError) as exc_info:
        workspace.check_export_format("STL")
    assert "STEP" in str(exc_info.value)


def test_stl_extension_without_format_rejected():
    with pytest.raises(errors.UnsupportedFormatError) as exc_info:
        workspace.check_export_format(None, filename="part.stl")
    assert "STEP" in str(exc_info.value)


@pytest.mark.parametrize("ok", [None, "", "STEP", "step", "Step", "svg"])
def test_supported_formats_pass(ok):
    workspace.check_export_format(
        ok, filename="part.step" if ok != "svg" else "part.svg"
    )


def test_jail_rejection_surfaces_as_iserror(server_context):
    import asyncio

    from cadquery_dxl_mcp.server import execute_tool

    result = asyncio.run(
        execute_tool(
            server_context,
            "save_workspace_module",
            {"module_filename": "../evil.py"},
            request_id="t1",
        )
    )
    assert result.is_error is True
    text = result.content[0].text
    assert "evil" in text or "outside" in text or "workspace" in text.lower()


def test_svg_filename_passes_through_unchanged(server_context):
    """Upstream owns the svg output dir (renders/); the jail validates only."""
    import asyncio

    import mcp_cadquery_server.handlers as h

    from cadquery_dxl_mcp.server import execute_tool

    result = asyncio.run(
        execute_tool(
            server_context,
            "export_shape_to_svg",
            {"result_id": "r_0", "filename": "part.svg"},
            request_id="t1",
        )
    )
    assert result.is_error is False
    assert h.CALLS[-1]["args"]["filename"] == "part.svg"


def test_svg_filename_with_directory_rejected(server_context):
    import asyncio

    from cadquery_dxl_mcp.server import execute_tool

    result = asyncio.run(
        execute_tool(
            server_context,
            "export_shape_to_svg",
            {"result_id": "r_0", "filename": "sub/part.svg"},
            request_id="t1",
        )
    )
    assert result.is_error is True


def test_export_shape_filename_rewritten_under_exports(server_context):
    import asyncio

    import mcp_cadquery_server.handlers as h

    from cadquery_dxl_mcp.server import execute_tool

    result = asyncio.run(
        execute_tool(
            server_context,
            "export_shape",
            {"result_id": "r_0", "filename": "part.step"},
            request_id="t1",
        )
    )
    assert result.is_error is False
    seen = h.CALLS[-1]["args"]["filename"]
    assert seen == str(server_context.workspace_root / "exports" / "part.step")


def test_receipt_paths_revalidated_on_reuse(server_context):
    """A previously returned absolute path still passes only if under the root."""
    root = server_context.workspace_root
    inside = root / "exports" / "part.step"
    assert workspace.resolve_call_workspace(root, str(inside)) == inside
    with pytest.raises(errors.WorkspaceEscapeError):
        workspace.resolve_call_workspace(root, str(root.parent / "other" / "part.step"))


def test_scan_part_library_defaults_to_workspace_root(server_context):
    """V5: an absent workspace_path must jail to the root, never upstream's default."""
    import asyncio

    import mcp_cadquery_server.handlers as h

    from cadquery_dxl_mcp.server import execute_tool

    result = asyncio.run(
        execute_tool(server_context, "scan_part_library", {}, request_id="t1")
    )
    assert result.is_error is False
    assert h.CALLS[-1]["tool"] == "scan_part_library"
    assert h.CALLS[-1]["args"]["workspace_path"] == str(server_context.workspace_root)


def test_scan_part_library_explicit_subdir_stays_jailed(server_context):
    """V5: an explicit workspace_path is still jailed; escapes stay isError."""
    import asyncio

    import mcp_cadquery_server.handlers as h

    from cadquery_dxl_mcp.server import execute_tool

    sub = server_context.workspace_root / "parts"
    sub.mkdir()
    ok = asyncio.run(
        execute_tool(
            server_context,
            "scan_part_library",
            {"workspace_path": str(sub)},
            request_id="t1",
        )
    )
    assert ok.is_error is False
    assert h.CALLS[-1]["args"]["workspace_path"] == str(sub)

    evil = asyncio.run(
        execute_tool(
            server_context,
            "scan_part_library",
            {"workspace_path": "../outside"},
            request_id="t2",
        )
    )
    assert evil.is_error is True


def test_shim_errors_leak_no_absolute_server_paths(server_context):
    """V6: the shim's own errors carry no absolute server paths.

    Upstream's verbatim OCC text may embed server paths by design (accepted
    disclosure, documented on UpstreamToolError); the shim itself must add
    none -- these three errors echo only caller-supplied relative values.
    """
    import asyncio
    import re

    from cadquery_dxl_mcp.server import execute_tool

    cases = [
        ("no_such_tool", {"query": "x"}),
        ("save_workspace_module", {"module_filename": "../evil.py"}),
        ("save_workspace_module", {"module_filename": "gear.txt"}),
    ]
    absolute = re.compile(r"[A-Za-z]:[\\/]|\\\\|/home/|/tmp/|/var/|SYSTEM")
    for tool_name, args in cases:
        result = asyncio.run(
            execute_tool(server_context, tool_name, args, request_id="t1")
        )
        assert result.is_error is True
        text = result.content[0].text
        assert not absolute.search(text), f"server path leaked: {text!r}"
        assert str(server_context.workspace_root) not in text
