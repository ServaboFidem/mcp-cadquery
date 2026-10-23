"""Fake of upstream ``mcp_api.py``: same envelope semantics as the real seam."""

from __future__ import annotations

from typing import Optional

from .handlers import tool_handlers


def process_tool_request(request: dict) -> Optional[dict]:
    """Processes a tool request synchronously, mirroring upstream's envelope."""
    request_id = request.get("request_id", "unknown")
    tool_name = request.get("tool_name")
    try:
        handler = tool_handlers.get(tool_name)
        if handler:
            result_message = handler(request)
        else:
            return {
                "type": "tool_error",
                "request_id": request_id,
                "error": f"Unknown tool: {tool_name}",
            }
    except Exception as e:
        detail = getattr(e, "detail", str(e))
        return {
            "type": "tool_error",
            "request_id": request_id,
            "error": f"Internal server error processing {tool_name}: {detail}",
        }
    if result_message is not None:
        return {
            "type": "tool_result",
            "request_id": request_id,
            "result": result_message,
        }
    return None
