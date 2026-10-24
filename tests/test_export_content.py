"""Export uploads: the shim PUTs bytes to R2, the result carries the link.

STEP/SVG/STL all land in artifact storage; the result stays a small JSON
summary with a presigned download URL. Bytes never transit MCP, so there
is no size cliff and no base64 detour. Reads happen only from jailed
locations the export just wrote.
"""

from __future__ import annotations

import asyncio
import json

from cadquery_dxl_mcp.server import _export_artifact, execute_tool


def _summary(result):
    assert result.is_error is False
    assert len(result.content) == 1
    return json.loads(result.content[0].text)


def test_export_shape_step_uploads_and_links(server_context, stub_s3):
    result = asyncio.run(
        execute_tool(
            server_context,
            "export_shape",
            {"result_id": "r_0", "filename": "part.step"},
            request_id="t1",
        )
    )
    summary = _summary(result)
    assert summary["artifact_key"] == "cadquery/t1/part.step"
    assert summary["artifact_url"].startswith(
        "https://fake-r2/fake-bucket/cadquery/t1/part.step"
    )
    assert summary["content_media_type"] == "model/step"
    stored = stub_s3.objects[("fake-bucket", "cadquery/t1/part.step")]
    assert stored["data"] == b"fake-step-content"
    assert summary["content_bytes"] == len(b"fake-step-content")


def test_export_shape_stl_uploads_binary_verbatim(server_context, stub_s3):
    result = asyncio.run(
        execute_tool(
            server_context,
            "export_shape",
            {"result_id": "r_0", "filename": "part.stl", "format": "STL"},
            request_id="t1",
        )
    )
    summary = _summary(result)
    assert summary["artifact_key"] == "cadquery/t1/part.stl"
    assert summary["content_media_type"] == "model/stl"
    stored = stub_s3.objects[("fake-bucket", "cadquery/t1/part.stl")]
    assert stored["data"] == b"FAKE-STL\x00\x01\x02-BINARY"


def test_export_svg_uploads_and_links(server_context, stub_s3):
    result = asyncio.run(
        execute_tool(
            server_context,
            "export_shape_to_svg",
            {"result_id": "r_0", "filename": "part.svg"},
            request_id="t1",
        )
    )
    summary = _summary(result)
    assert summary["content_media_type"] == "image/svg+xml"
    assert summary["artifact_url"].startswith("https://fake-r2/fake-bucket/")
    stored = stub_s3.objects[
        ("fake-bucket", summary["artifact_key"])
    ]
    assert stored["data"] == b"fake-svg-content"


def test_export_result_outside_root_is_error(server_context):
    outside = server_context.workspace_root.parent / "evil.step"
    result = _export_artifact(
        server_context,
        "export_shape_to_svg",
        {},
        {"success": True, "filename": str(outside)},
        "t1",
    )
    assert result.is_error is True
    assert "workspace" in result.content[0].text.lower()


def test_export_result_missing_file_is_error(server_context):
    missing = server_context.workspace_root / "exports" / "ghost.step"
    result = _export_artifact(
        server_context,
        "export_shape",
        {"filename": str(missing)},
        {"success": True, "filename": str(missing)},
        "t1",
    )
    assert result.is_error is True
    assert "missing" in result.content[0].text.lower()
