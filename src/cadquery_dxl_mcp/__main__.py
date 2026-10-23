"""Command line: ``python -m cadquery_dxl_mcp serve --workspace-dir PATH``.

Production spawn (never ``uv run`` -- a grandchild python would outlive the
supervisor's ``kill_on_drop``)::

    <venv>\\Scripts\\python.exe -I -m cadquery_dxl_mcp serve --workspace-dir <data_dir>\\cadquery\\workspace

Stdout carries only MCP frames. Logging goes to stderr as JSON lines.
``serve`` fails closed: a missing workspace root or a failed CadQuery import
exits non-zero naming the cause, before serving anything. A set
``CADQUERY_DXL_MCP_UPSTREAM_SRC`` hatch does not fail closed -- it is the
documented escape hatch for an alternate upstream checkout -- but it warns
to stderr so a production process running off an unexpected tree is visible
in the service log; production leaves it unset (the venv owns the path).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key in ("event", "tool", "call_id"):
            if hasattr(record, key):
                payload[key] = getattr(record, key)
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def _configure_logging() -> None:
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(_JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(logging.INFO)


def build_prod_spawn(python_exe: str, workspace_dir: str) -> list[str]:
    """The exact production argv: direct venv python, isolated, module serve."""
    return [
        python_exe,
        "-I",
        "-m",
        "cadquery_dxl_mcp",
        "serve",
        "--workspace-dir",
        workspace_dir,
    ]


def serve(workspace_dir: str) -> None:
    from .server import ServerContext, build_server
    from .upstream import UPSTREAM_SRC_ENV, load_upstream, upstream_src_override

    override = upstream_src_override()
    if override is not None:
        message = (
            f"warning: {UPSTREAM_SRC_ENV} is set to {override!r}; "
            "production leaves it unset (the venv owns the path)"
        )
        print(message, file=sys.stderr)
    root = Path(workspace_dir)
    if not root.is_dir():
        print(f"workspace root does not exist: {workspace_dir}", file=sys.stderr)
        raise SystemExit(f"workspace root does not exist: {workspace_dir}")
    try:
        import cadquery  # noqa: F401 -- preflight: fail closed when OCC is unavailable
    except Exception as exc:
        print(f"cadquery import failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(
            f"cadquery import failed: {type(exc).__name__}: {exc}"
        ) from None
    ctx = ServerContext(workspace_root=root, upstream=load_upstream())
    server = build_server(ctx)
    asyncio.run(server.run_stdio_async())


def main(argv: list[str] | None = None) -> None:
    _configure_logging()
    parser = argparse.ArgumentParser(prog="cadquery-dxl-mcp")
    parser.add_argument("command", choices=("serve",))
    parser.add_argument("--workspace-dir", required=True)
    ns = parser.parse_args(argv)
    if ns.command == "serve":
        serve(ns.workspace_dir)


if __name__ == "__main__":
    main()
