"""Fake of upstream ``handlers.py``: canned results, real seam shapes.

Dict-style handlers take ``request`` (``{"tool_name", "request_id",
"arguments"}``) and read ``request["arguments"]``. The execute handler takes
``(args: ExecuteCadqueryScriptArgs, request_id)`` -- the signature mismatch
with ``process_tool_request`` is the point (see package docstring).

``PRINT_ON_CALL`` names tools whose fake handler does a bare ``print()``,
proving the shim captures handler stdout instead of leaking MCP-corrupting
frames. ``SLEEP_ON_CALL`` maps a tool name to seconds to sleep, for the
cancellation test. ``FAIL_ONCE`` maps a tool name to an error message the
fake raises once, for the isError tests.
"""

from __future__ import annotations

import time
from typing import Any

from .models import ExecuteCadqueryScriptArgs

PRINT_ON_CALL: set[str] = set()
SLEEP_ON_CALL: dict[str, float] = {}
FAIL_ONCE: dict[str, str] = {}
CALLS: list[dict[str, Any]] = []


def _maybe_misbehave(tool_name: str) -> None:
    if tool_name in PRINT_ON_CALL:
        print(f"fake upstream noise from {tool_name}")
    if tool_name in SLEEP_ON_CALL:
        time.sleep(SLEEP_ON_CALL[tool_name])
    if tool_name in FAIL_ONCE:
        raise RuntimeError(FAIL_ONCE.pop(tool_name))


def handle_execute_cadquery_script(
    args: ExecuteCadqueryScriptArgs, request_id: str = "unknown"
) -> dict:
    """Handles the 'execute_cadquery_script' tool request."""
    _maybe_misbehave("execute_cadquery_script")
    CALLS.append(
        {"tool": "execute_cadquery_script", "request_id": request_id, "args": args}
    )
    return {
        "success": True,
        "message": "fake script ok",
        "results": [
            {
                "result_id": f"{request_id}_0",
                "success": True,
                "shapes_count": 1,
                "error": None,
            }
        ],
    }


def _dict_handler(tool_name: str):
    def handle(request: dict) -> dict:
        """Handles the tool request."""
        _maybe_misbehave(tool_name)
        args = request.get("arguments", {})
        CALLS.append(
            {"tool": tool_name, "request_id": request.get("request_id"), "args": args}
        )
        if tool_name == "export_shape":
            return {
                "success": True,
                "message": "fake export ok",
                "filename": args.get("filename"),
            }
        if tool_name == "export_shape_to_svg":
            return {
                "success": True,
                "message": "fake svg ok",
                "filename": args.get("filename"),
            }
        if tool_name == "scan_part_library":
            return {"success": True, "parts": []}
        if tool_name == "search_parts":
            return {"success": True, "matches": []}
        if tool_name == "save_workspace_module":
            return {"success": True, "module": args.get("module_filename")}
        if tool_name == "get_shape_properties":
            return {"success": True, "volume": 1.0}
        if tool_name == "get_shape_description":
            return {"success": True, "description": "a fake box"}
        if tool_name == "launch_cq_editor":
            return {"success": True, "message": "fake editor launched"}
        if tool_name == "install_workspace_package":
            return {"success": True, "message": "fake pip install ok"}
        raise AssertionError(f"fake has no canned result for {tool_name}")

    handle.__name__ = f"handle_{tool_name}"
    return handle


handle_export_shape = _dict_handler("export_shape")
handle_export_shape_to_svg = _dict_handler("export_shape_to_svg")
handle_scan_part_library = _dict_handler("scan_part_library")
handle_search_parts = _dict_handler("search_parts")
handle_save_workspace_module = _dict_handler("save_workspace_module")
handle_install_workspace_package = _dict_handler("install_workspace_package")
handle_launch_cq_editor = _dict_handler("launch_cq_editor")
handle_get_shape_properties = _dict_handler("get_shape_properties")
handle_get_shape_description = _dict_handler("get_shape_description")

tool_handlers = {
    "execute_cadquery_script": handle_execute_cadquery_script,
    "export_shape": handle_export_shape,
    "export_shape_to_svg": handle_export_shape_to_svg,
    "scan_part_library": handle_scan_part_library,
    "search_parts": handle_search_parts,
    "save_workspace_module": handle_save_workspace_module,
    "install_workspace_package": handle_install_workspace_package,
    "launch_cq_editor": handle_launch_cq_editor,
    "get_shape_properties": handle_get_shape_properties,
    "get_shape_description": handle_get_shape_description,
}
