"""Export content attachment: the shim returns file bytes, not just paths.

STEP/SVG ride as UTF-8 text, STL base64-encoded (binary bytes are not valid
artifact text; base64 is, so the proxy spillover + S3 mirror carry it like
any large result). Reads happen only from jailed locations.
"""

from __future__ import annotations

import asyncio
import base64
import json

from cadquery_dxl_mcp.server import _export_result, execute_tool


def _summary(result):
    assert result.is_error is False
    assert len(result.content) == 2
    return json.loads(result.content[0].text)


def test_export_shape_step_returns_text_content(server_context):
    result = asyncio.run(
        execute_tool(
            server_context,
            "export_shape",
            {"result_id": "r_0", "filename": "part.step"},
            request_id="t1",
        )
    )
    summary = _summary(result)
    assert summary["content_encoding"] == "utf-8"
    assert summary["content_bytes"] == len("fake-step-content")
    assert summary["content_filename"] == "part.step"
    assert result.content[1].text == "fake-step-content"


def test_export_shape_stl_returns_base64_content(server_context):
    result = asyncio.run(
        execute_tool(
            server_context,
            "export_shape",
            {"result_id": "r_0", "filename": "part.stl"},
            request_id="t1",
        )
    )
    summary = _summary(result)
    assert summary["content_encoding"] == "base64"
    assert summary["content_media_type"] == "model/stl"
    assert base64.b64decode(result.content[1].text) == b"FAKE-STL\x00\x01\x02-BINARY"


def test_export_svg_returns_text_content(server_context):
    result = asyncio.run(
        execute_tool(
            server_context,
            "export_shape_to_svg",
            {"result_id": "r_0", "filename": "part.svg"},
            request_id="t1",
        )
    )
    summary = _summary(result)
    assert summary["content_encoding"] == "utf-8"
    assert summary["content_media_type"] == "image/svg+xml"
    assert result.content[1].text == "fake-svg-content"


def test_export_result_outside_root_is_error(server_context):
    outside = server_context.workspace_root.parent / "evil.step"
    result = _export_result(
        server_context,
        "export_shape_to_svg",
        {},
        {"success": True, "filename": str(outside)},
    )
    assert result.is_error is True
    assert "workspace" in result.content[0].text.lower()


def test_export_result_missing_file_is_error(server_context):
    missing = server_context.workspace_root / "exports" / "ghost.step"
    result = _export_result(
        server_context,
        "export_shape",
        {"filename": str(missing)},
        {"success": True, "filename": str(missing)},
    )
    assert result.is_error is True
    assert "missing" in result.content[0].text.lower()
