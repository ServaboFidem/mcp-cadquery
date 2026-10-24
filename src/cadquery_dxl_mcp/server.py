"""FastMCP stdio server: the 8 allowlisted CadQuery tools over real MCP stdio.

A fresh ``MCPServer`` app (mcp >= 2.2); upstream's custom stdio/SSE framing
code stays out of the process entirely -- only the handler seam in
:mod:`cadquery_dxl_mcp.upstream` is imported.

Envelope rules (the spec's fixed floor):
- Success returns upstream's ``result`` verbatim as JSON text.
- Export tools (``export_shape``, ``export_shape_to_svg``) append the
  exported file as a second text block -- STEP/SVG as UTF-8 text, STL
  base64-encoded (binary bytes are not valid artifact text, base64 is, so
  the proxy's spillover + S3 mirror carry it like any large result). The
  summary names the encoding; the file is read back only from the jailed
  location the export just wrote, never from a caller-supplied path.
- Every tool failure -- jail rejection, unsupported format, upstream
  ``tool_error``, bad arguments -- is ``CallToolResult(is_error=True)``.
  Tool failures are never transport errors; the backend keeps serving.
- Upstream runs in a worker thread (``anyio.to_thread``), so a long OCC call
  honors cancellation: the waiter is freed while the next call still gets a
  clean stream.
"""

from __future__ import annotations

import base64
import json
import logging
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import anyio.to_thread

from mcp.server.mcpserver import MCPServer

from mcp.types import CallToolResult, TextContent

from . import __version__
from .errors import ShimError
from .upstream import Upstream, dispatch
from .workspace import (
    check_export_filename,
    check_export_format,
    check_module_filename,
    export_target_path,
    resolve_call_workspace,
)

log = logging.getLogger(__name__)

SERVER_NAME = "cadquery-dxl-mcp"

#: The eight exposed tools, in spec order. Everything else upstream serves --
#: ``launch_cq_editor`` (needs an interactive desktop) and
#: ``install_workspace_package`` (pip-installs into the hardened tree at call
#: time) -- is absent from this server under any arguments.
ALLOWLIST: tuple[str, ...] = (
    "execute_cadquery_script",
    "export_shape",
    "export_shape_to_svg",
    "scan_part_library",
    "search_parts",
    "save_workspace_module",
    "get_shape_properties",
    "get_shape_description",
)

#: Tools present upstream but never registered here.
ABSENT_TOOLS: tuple[str, ...] = ("launch_cq_editor", "install_workspace_package")

#: Tools whose upstream handler requires ``workspace_path`` (raises when missing).
#: ``scan_part_library`` is one of them (V5): an absent path defaults to the
#: root so the call can never run against upstream's default library dir.
_WORKSPACE_REQUIRED = frozenset(
    {
        "execute_cadquery_script",
        "export_shape",
        "export_shape_to_svg",
        "save_workspace_module",
        "scan_part_library",
    }
)

_DESCRIPTIONS = {
    "execute_cadquery_script": "Run a CadQuery script in the workspace; returns a result_id for later export and inspection.",
    "export_shape": "Export a built shape and return its bytes: STEP as text, STL base64-encoded.",
    "export_shape_to_svg": "Render a built shape and return the SVG text.",
    "scan_part_library": "Index the part library under the workspace.",
    "search_parts": "Search indexed part metadata (read-only).",
    "save_workspace_module": "Save a .py helper module into the workspace.",
    "get_shape_properties": "Geometric properties of a built shape (read-only).",
    "get_shape_description": "Human-readable description of a built shape (read-only).",
}


@dataclass(frozen=True)
class ServerContext:
    """Everything a tool call needs: the jail root and the loaded upstream seam."""

    workspace_root: Path
    upstream: Upstream


def _new_request_id() -> str:
    return uuid.uuid4().hex[:12]


def jailed_arguments(
    ctx: ServerContext, tool_name: str, arguments: Mapping[str, Any]
) -> dict[str, Any]:
    """Apply the jail to caller arguments; violations raise typed shim errors.

    ``workspace_path`` defaults to the root where upstream requires it
    (including ``scan_part_library`` -- V5: it must never run against
    upstream's default library dir) and is otherwise passed through only
    when the caller gave it (so upstream defaults such as the part-library
    search index keep working for tools that do not need a workspace).
    ``export_shape`` filenames are rewritten to ``<root>/exports/<basename>``
    -- absolute paths are computed by the shim, never taken from the caller.
    The svg filename is only validated: upstream basenames it itself and
    writes into ``<workspace>/shapes/renders/``, so rewriting it would change
    the verbatim result contract.
    """
    args = dict(arguments)
    if tool_name not in ALLOWLIST:
        from .errors import UpstreamToolError

        raise UpstreamToolError(f"Unknown tool: {tool_name}")

    if "workspace_path" in args and args["workspace_path"] is not None:
        args["workspace_path"] = str(
            resolve_call_workspace(ctx.workspace_root, str(args["workspace_path"]))
        )
    elif tool_name in _WORKSPACE_REQUIRED:
        args["workspace_path"] = str(ctx.workspace_root)

    if tool_name == "export_shape":
        filename = args.get("filename")
        check_export_format(
            args.get("format"), filename if isinstance(filename, str) else None
        )
        args["filename"] = str(export_target_path(ctx.workspace_root, str(filename)))
    elif tool_name == "export_shape_to_svg":
        filename = args.get("filename")
        if filename is not None:
            args["filename"] = check_export_filename(str(filename))
    elif tool_name == "save_workspace_module":
        module_filename = args.get("module_filename")
        args["module_filename"] = check_module_filename(str(module_filename))

    # Upstream treats an explicit null differently from an absent key
    # (e.g. ``options=None`` fails its isinstance check), so drop nulls and
    # let upstream defaults apply.
    return {k: v for k, v in args.items() if v is not None}


def _result_text(result: Any) -> str:
    try:
        return json.dumps(result, default=str)
    except Exception:
        return str(result)


def _ok(result: Any) -> CallToolResult:
    return CallToolResult(
        content=[TextContent(type="text", text=_result_text(result))], is_error=False
    )


def _tool_error(message: str) -> CallToolResult:
    return CallToolResult(
        content=[TextContent(type="text", text=message)], is_error=True
    )


async def execute_tool(
    ctx: ServerContext, tool_name: str, arguments: Mapping[str, Any], *, request_id: str
) -> CallToolResult:
    """Run one tool call: jail, dispatch on a worker thread, envelope the answer."""
    try:
        jailed = jailed_arguments(ctx, tool_name, arguments)
    except ShimError as exc:
        log.info("tool %r rejected: %s", tool_name, exc)
        return _tool_error(str(exc))
    try:
        result = await anyio.to_thread.run_sync(
            lambda: dispatch(ctx.upstream, tool_name, request_id, jailed)
        )
    except ShimError as exc:
        log.info("tool %r failed: %s", tool_name, exc)
        return _tool_error(str(exc))
    if tool_name in ("export_shape", "export_shape_to_svg"):
        return _export_result(ctx, tool_name, jailed, result)
    return _ok(result)


def _export_result(
    ctx: ServerContext, tool_name: str, jailed: Mapping[str, Any], result: Any
) -> CallToolResult:
    """Attach the exported file to a successful export call.

    The file is read back ONLY from the jailed location -- the shim-computed
    ``exports/`` path for ``export_shape``, or the upstream-reported path
    re-validated under the workspace root for SVG. A result that points
    outside the root, or at a file that is not there, is an ``isError``:
    the export did not land where the jail guarantees, and serving a path
    the caller cannot use (or bytes from elsewhere) would be worse.
    """
    if tool_name == "export_shape":
        raw: Any = jailed.get("filename")
    elif isinstance(result, dict):
        raw = result.get("filename")
    else:
        raw = None
    if not isinstance(raw, str) or not raw:
        return _tool_error(f"{tool_name} returned no filename")
    try:
        path = Path(raw)
        if not path.is_absolute():
            path = ctx.workspace_root / path
        path.resolve().relative_to(ctx.workspace_root.resolve())
    except (OSError, ValueError):
        return _tool_error(f"{tool_name} filename escapes the workspace")
    try:
        data = path.read_bytes()
    except OSError:
        return _tool_error(f"{tool_name} output file is missing: {path.name}")
    if path.suffix.lower() == ".stl":
        payload = base64.b64encode(data).decode("ascii")
        encoding = "base64"
        media_type = "model/stl"
    else:
        try:
            payload = data.decode("utf-8")
            encoding = "utf-8"
        except UnicodeDecodeError:
            payload = base64.b64encode(data).decode("ascii")
            encoding = "base64"
        media_type = "model/step" if tool_name == "export_shape" else "image/svg+xml"
    summary = dict(result) if isinstance(result, dict) else {"result": result}
    summary.update(
        {
            "content_encoding": encoding,
            "content_media_type": media_type,
            "content_bytes": len(data),
            "content_filename": path.name,
        }
    )
    return CallToolResult(
        content=[
            TextContent(type="text", text=_result_text(summary)),
            TextContent(type="text", text=payload),
        ],
        is_error=False,
    )


def _present(arguments: Mapping[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in dict(arguments).items() if v is not None}


def build_server(ctx: ServerContext) -> MCPServer:
    """Build the MCP server with exactly the allowlisted tools registered."""
    server = MCPServer(
        name=SERVER_NAME,
        version=__version__,
        instructions=(
            "Parametric CAD (CadQuery/OCC) inside a workspace jail. "
            "Every server-side path stays under the workspace root; "
            "exports return their bytes (STEP/SVG as text, STL base64)."
        ),
    )

    @server.tool(
        name="execute_cadquery_script",
        description=_DESCRIPTIONS["execute_cadquery_script"],
    )
    async def execute_cadquery_script(
        script: str | None = None,
        workspace_path: str | None = None,
        parameters: dict[str, Any] | None = None,
        parameter_sets: list[dict[str, Any]] | None = None,
    ) -> CallToolResult:
        return await execute_tool(
            ctx,
            "execute_cadquery_script",
            _present(
                {
                    "script": script,
                    "workspace_path": workspace_path,
                    "parameters": parameters,
                    "parameter_sets": parameter_sets,
                }
            ),
            request_id=_new_request_id(),
        )

    @server.tool(name="export_shape", description=_DESCRIPTIONS["export_shape"])
    async def export_shape(
        result_id: str | None = None,
        filename: str | None = None,
        workspace_path: str | None = None,
        shape_index: int | None = None,
        format: str | None = None,
        options: dict[str, Any] | None = None,
    ) -> CallToolResult:
        return await execute_tool(
            ctx,
            "export_shape",
            _present(
                {
                    "result_id": result_id,
                    "filename": filename,
                    "workspace_path": workspace_path,
                    "shape_index": shape_index,
                    "format": format,
                    "options": options,
                }
            ),
            request_id=_new_request_id(),
        )

    @server.tool(
        name="export_shape_to_svg", description=_DESCRIPTIONS["export_shape_to_svg"]
    )
    async def export_shape_to_svg(
        result_id: str | None = None,
        workspace_path: str | None = None,
        shape_index: int | None = None,
        filename: str | None = None,
        options: dict[str, Any] | None = None,
    ) -> CallToolResult:
        return await execute_tool(
            ctx,
            "export_shape_to_svg",
            _present(
                {
                    "result_id": result_id,
                    "workspace_path": workspace_path,
                    "shape_index": shape_index,
                    "filename": filename,
                    "options": options,
                }
            ),
            request_id=_new_request_id(),
        )

    @server.tool(
        name="scan_part_library", description=_DESCRIPTIONS["scan_part_library"]
    )
    async def scan_part_library(workspace_path: str | None = None) -> CallToolResult:
        return await execute_tool(
            ctx,
            "scan_part_library",
            _present({"workspace_path": workspace_path}),
            request_id=_new_request_id(),
        )

    @server.tool(name="search_parts", description=_DESCRIPTIONS["search_parts"])
    async def search_parts(query: str | None = None) -> CallToolResult:
        return await execute_tool(
            ctx,
            "search_parts",
            _present({"query": query}),
            request_id=_new_request_id(),
        )

    @server.tool(
        name="save_workspace_module", description=_DESCRIPTIONS["save_workspace_module"]
    )
    async def save_workspace_module(
        module_filename: str | None = None,
        module_content: str | None = None,
        workspace_path: str | None = None,
    ) -> CallToolResult:
        return await execute_tool(
            ctx,
            "save_workspace_module",
            _present(
                {
                    "module_filename": module_filename,
                    "module_content": module_content,
                    "workspace_path": workspace_path,
                }
            ),
            request_id=_new_request_id(),
        )

    @server.tool(
        name="get_shape_properties", description=_DESCRIPTIONS["get_shape_properties"]
    )
    async def get_shape_properties(
        result_id: str | None = None, shape_index: int | None = None
    ) -> CallToolResult:
        return await execute_tool(
            ctx,
            "get_shape_properties",
            _present({"result_id": result_id, "shape_index": shape_index}),
            request_id=_new_request_id(),
        )

    @server.tool(
        name="get_shape_description", description=_DESCRIPTIONS["get_shape_description"]
    )
    async def get_shape_description(
        result_id: str | None = None, shape_index: int | None = None
    ) -> CallToolResult:
        return await execute_tool(
            ctx,
            "get_shape_description",
            _present({"result_id": result_id, "shape_index": shape_index}),
            request_id=_new_request_id(),
        )

    return server
