"""Upstream seam loader and dispatch.

The seam is ``mcp_cadquery_server.mcp_api.process_tool_request`` over
``mcp_cadquery_server.handlers.tool_handlers`` (verified against the pinned
upstream, master @ eae44ca8 -- see tests/test_upstream.py, which pins the
names so a rename breaks loudly in the suite, not in production).

One documented adaptation: ``process_tool_request`` calls every handler as
``handler(request_dict)``, but ``handle_execute_cadquery_script`` takes typed
``(args: ExecuteCadqueryScriptArgs, request_id)`` -- a dict has no
``.workspace_path``, so the uniform path can only ever yield a tool_error
for that tool. The shim therefore dispatches ``execute_cadquery_script``
through the typed handler directly (same function, same result verbatim) and
every other allowlisted tool through ``process_tool_request`` untouched.
Nothing is reimplemented: OCC still runs entirely inside upstream code.

Stdout discipline: the dispatch runs with ``sys.stdout`` redirected into a
buffer that is re-logged to stderr afterwards. Upstream's in-process modules
at the pin contain no ``print`` (audited 2026-10-23); the one module that
does print, ``script_runner.py``, runs as a captured subprocess. The redirect
is belt-and-suspenders so a future upstream ``print`` corrupts nothing --
stdout stays MCP frames only.
"""

from __future__ import annotations

import contextlib
import importlib
import io
import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

from .errors import UpstreamImportError, UpstreamToolError

log = logging.getLogger(__name__)

#: Env var naming an extra directory prepended to ``sys.path`` before the
#: upstream import. Production leaves it unset (the venv owns the path) --
#: ``serve`` in :mod:`cadquery_dxl_mcp.__main__` warns to stderr whenever it
#: is set, so a set hatch is visible in the service log, and the verify gate
#: asserts the production value. Tests point it at the fixture fake. It
#: doubles as the escape hatch for an alternate upstream checkout; ``-I``
#: ignores ``PYTHON*`` but not this variable, so whoever controls the
#: service environment controls what code is imported.
UPSTREAM_SRC_ENV = "CADQUERY_DXL_MCP_UPSTREAM_SRC"

EXECUTE_TOOL = "execute_cadquery_script"


@dataclass(frozen=True)
class Upstream:
    """The loaded seam: the envelope plus the handler table plus the args model."""

    process_tool_request: Callable[[dict[str, Any]], dict[str, Any] | None]
    tool_handlers: Mapping[str, Callable[..., Any]]
    execute_args_model: Any


def upstream_src_override() -> str | None:
    """The hatch value, or ``None`` on the production-clean path (unset/blank)."""
    value = os.environ.get(UPSTREAM_SRC_ENV, "").strip()
    return value or None


def load_upstream() -> Upstream:
    """Import the upstream seam lazily. Importing this module never touches OCC."""
    extra = upstream_src_override()
    if extra:
        # The hatch names the tree to import from, so it goes first even when
        # already on sys.path (e.g. via PYTHONPATH): otherwise a real upstream
        # sitting beside the shim in the same checkout shadows the named tree
        # and the override silently imports the wrong code.
        try:
            sys.path.remove(extra)
        except ValueError:
            pass
        sys.path.insert(0, extra)
    else:
        # Sibling-checkout fallback: <mcps/cadquery>/src next to this package.
        here = Path(__file__).resolve()
        sibling = here.parent.parent.parent / "mcp_cadquery_server"
        if sibling.is_dir():
            sys.path.insert(0, str(sibling.parent))
    try:
        mcp_api = importlib.import_module("mcp_cadquery_server.mcp_api")
        handlers = importlib.import_module("mcp_cadquery_server.handlers")
        models = importlib.import_module("mcp_cadquery_server.models")
    except Exception as exc:
        raise UpstreamImportError(
            f"could not import upstream seam mcp_cadquery_server: {exc}"
        ) from None
    try:
        process_tool_request = mcp_api.process_tool_request
        tool_handlers = handlers.tool_handlers
        execute_args_model = models.ExecuteCadqueryScriptArgs
    except AttributeError as exc:
        raise UpstreamImportError(
            f"upstream seam renamed a member the shim needs: {exc}"
        ) from None
    if not callable(process_tool_request) or not isinstance(tool_handlers, dict):
        raise UpstreamImportError("upstream seam has an unexpected shape")
    return Upstream(
        process_tool_request=process_tool_request,
        tool_handlers=tool_handlers,
        execute_args_model=execute_args_model,
    )


def _validation_fields(exc: Exception) -> str:
    errors = getattr(exc, "errors", None)
    if callable(errors):
        try:
            return ", ".join(
                ".".join(str(part) for part in err.get("loc", ())) or "?"
                for err in errors()
            )
        except Exception:
            pass
    return str(exc)


def dispatch(
    up: Upstream, tool_name: str, request_id: str, arguments: Mapping[str, Any]
) -> Any:
    """Call upstream for one tool; return its ``result`` verbatim.

    Raises :class:`UpstreamToolError` for tool-level failures (unknown tool,
    upstream ``tool_error``, empty reply, bad arguments). Transport errors are
    never raised here -- a bad script is ``isError``, not a broken backend.

    The allowlist is enforced here as well as in ``jailed_arguments`` and MCP
    registration (V3 second lock): a non-allowlisted name fails even when
    its handler exists upstream, however dispatch is reached. The import is
    lazy because ``server`` imports this module at its top level.

    The stdout redirect is process-global, so concurrent dispatches would
    share one buffer; the proxy bounds this child to a single flight
    (``max_concurrent_calls = 1``), which is what makes the capture exact.
    """
    from .server import ALLOWLIST

    if tool_name not in ALLOWLIST:
        raise UpstreamToolError(f"Unknown tool: {tool_name}")
    handler = up.tool_handlers.get(tool_name)
    if handler is None and tool_name != EXECUTE_TOOL:
        raise UpstreamToolError(f"Unknown tool: {tool_name}")
    buffer = io.StringIO()
    try:
        with contextlib.redirect_stdout(buffer):
            if tool_name == EXECUTE_TOOL:
                result = _call_execute(up, dict(arguments), request_id)
            else:
                result = _call_via_envelope(up, tool_name, request_id, dict(arguments))
    finally:
        captured = buffer.getvalue()
    if captured.strip():
        log.warning(
            "upstream stdout captured (%d bytes); re-logged, never sent on stdout",
            len(captured),
            extra={"event": "upstream_stdout_captured", "tool": tool_name},
        )
        for line in captured.splitlines():
            log.warning("upstream-stdout: %s", line)
    return result


def _call_execute(up: Upstream, arguments: dict[str, Any], request_id: str) -> Any:
    try:
        args = up.execute_args_model(**arguments)
    except Exception as exc:
        raise UpstreamToolError(
            f"Invalid arguments for execute_cadquery_script ({_validation_fields(exc)})"
        ) from None
    handler = up.tool_handlers.get(EXECUTE_TOOL)
    if handler is None:
        raise UpstreamToolError(f"Unknown tool: {EXECUTE_TOOL}")
    try:
        return handler(args, request_id)
    except UpstreamToolError:
        raise
    except Exception as exc:
        # Mirror mcp_api.process_tool_request's envelope so the failure reads
        # exactly like upstream's own internal-error shape.
        detail = getattr(exc, "detail", str(exc))
        raise UpstreamToolError(
            f"Internal server error processing {EXECUTE_TOOL}: {detail}"
        ) from None


def _call_via_envelope(
    up: Upstream, tool_name: str, request_id: str, arguments: dict[str, Any]
) -> Any:
    message = up.process_tool_request(
        {"tool_name": tool_name, "request_id": request_id, "arguments": arguments}
    )
    if message is None:
        raise UpstreamToolError(f"Upstream returned no result for {tool_name}")
    if not isinstance(message, dict):
        raise UpstreamToolError(f"Upstream returned a malformed reply for {tool_name}")
    if message.get("type") == "tool_error":
        raise UpstreamToolError(
            str(message.get("error", f"{tool_name} failed with no message"))
        )
    if message.get("type") != "tool_result" or "result" not in message:
        raise UpstreamToolError(f"Upstream returned a malformed reply for {tool_name}")
    return message["result"]
