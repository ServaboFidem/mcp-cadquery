"""Fake upstream ``mcp_cadquery_server`` package for unit tests.

Mirrors the seam of the pinned upstream (master @ eae44ca8) without
importing CadQuery/OCC: ``handlers.tool_handlers``, ``mcp_api`` with
``process_tool_request(request: dict)``, and ``models`` with
``ExecuteCadqueryScriptArgs``.

The quirks are deliberate reproductions, not accidents:
- ``handle_execute_cadquery_script`` takes typed ``(args, request_id)``
  while ``process_tool_request`` calls every handler as ``handler(request)``,
  so going through ``process_tool_request`` for that tool yields a tool_error
  (a dict has no ``.workspace_path``). The shim must adapt that one call.
- ``handle_export_shape`` honors absolute/dir-containing filenames, which is
  exactly the traversal vector the shim jail closes before upstream sees it.
"""

from . import handlers, mcp_api, models  # noqa: F401

__all__ = ["handlers", "mcp_api", "models"]
