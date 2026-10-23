"""Upstream seam: verbatim results, isError mapping, stdout capture, seam names."""

from __future__ import annotations

import pytest

from cadquery_dxl_mcp import errors
from cadquery_dxl_mcp import upstream as upstream_mod


def test_loader_exposes_verified_seam_names(loaded_upstream):
    """Pin the actual upstream names; a rename breaks loudly here, not in prod."""
    assert callable(loaded_upstream.process_tool_request)
    assert isinstance(loaded_upstream.tool_handlers, dict)
    assert "process_tool_request" in dir(
        __import__("mcp_cadquery_server.mcp_api", fromlist=["x"])
    )
    assert "tool_handlers" in dir(
        __import__("mcp_cadquery_server.handlers", fromlist=["x"])
    )


def test_dict_tool_result_returned_verbatim(loaded_upstream):
    result = upstream_mod.dispatch(
        loaded_upstream, "search_parts", "r1", {"query": "gear"}
    )
    assert result == {"success": True, "matches": []}


def test_upstream_tool_error_becomes_typed_error(loaded_upstream):
    import mcp_cadquery_server.handlers as h

    h.FAIL_ONCE["search_parts"] = "boom"
    with pytest.raises(errors.UpstreamToolError) as exc_info:
        upstream_mod.dispatch(loaded_upstream, "search_parts", "r1", {"query": "x"})
    assert "boom" in str(exc_info.value)


def test_execute_uses_typed_handler_seam(loaded_upstream):
    """execute goes through the typed (args, request_id) handler, not the broken dict path."""
    result = upstream_mod.dispatch(
        loaded_upstream,
        "execute_cadquery_script",
        "r9",
        {"workspace_path": "/ws", "script": "s"},
    )
    assert result["success"] is True
    assert result["results"][0]["result_id"] == "r9_0"

    import mcp_cadquery_server.handlers as h

    call = h.CALLS[-1]
    assert call["tool"] == "execute_cadquery_script"
    assert call["request_id"] == "r9"
    # The handler received a real args model, not the raw dict.
    assert type(call["args"]).__name__ == "ExecuteCadqueryScriptArgs"
    assert call["args"].script == "s"


def test_execute_argument_validation_is_typed_error(loaded_upstream):
    with pytest.raises(errors.UpstreamToolError) as exc_info:
        upstream_mod.dispatch(
            loaded_upstream, "execute_cadquery_script", "r1", {"workspace_path": "/ws"}
        )
    assert "script" in str(exc_info.value)


def test_handler_stdout_is_captured_not_leaked(loaded_upstream, capsys):
    import mcp_cadquery_server.handlers as h

    h.PRINT_ON_CALL.add("search_parts")
    result = upstream_mod.dispatch(
        loaded_upstream, "search_parts", "r1", {"query": "gear"}
    )
    assert result == {"success": True, "matches": []}
    out, _ = capsys.readouterr()
    assert out == "", f"handler stdout leaked: {out!r}"


def test_unknown_tool_is_typed_error(loaded_upstream):
    with pytest.raises(errors.UpstreamToolError):
        upstream_mod.dispatch(loaded_upstream, "nope", "r1", {})


@pytest.mark.parametrize("absent", ["install_workspace_package", "launch_cq_editor"])
def test_dispatch_rejects_non_allowlisted_upstream_tool(loaded_upstream, absent):
    """V3 second lock: the handler exists upstream, but dispatch refuses it.

    ``execute_tool`` maps this typed error to isError, so a direct dispatch
    can never become a live eleventh tool however it is reached.
    """
    assert absent in loaded_upstream.tool_handlers
    with pytest.raises(errors.UpstreamToolError) as exc_info:
        upstream_mod.dispatch(loaded_upstream, absent, "r1", {})
    assert "Unknown tool" in str(exc_info.value)


def test_upstream_src_override_defaults_to_none(monkeypatch):
    """V7e: production leaves the hatch unset."""
    monkeypatch.delenv(upstream_mod.UPSTREAM_SRC_ENV, raising=False)
    assert upstream_mod.upstream_src_override() is None


def test_upstream_src_override_blank_is_none(monkeypatch):
    monkeypatch.setenv(upstream_mod.UPSTREAM_SRC_ENV, "   ")
    assert upstream_mod.upstream_src_override() is None


def test_upstream_src_override_returns_value(monkeypatch, tmp_path):
    monkeypatch.setenv(upstream_mod.UPSTREAM_SRC_ENV, str(tmp_path))
    assert upstream_mod.upstream_src_override() == str(tmp_path)
