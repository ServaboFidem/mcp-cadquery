"""Typed shim errors.

Every failure a tool can report travels as an MCP ``CallToolResult`` with
``is_error=True``; nothing here is ever raised as a JSON-RPC transport error.
Keeping the hierarchy typed (never bare ``Exception`` / stringly failures)
is what lets the dispatch layer map each class to the right envelope.
"""

from __future__ import annotations


class ShimError(Exception):
    """Base for every error the shim itself raises. Never crosses the wire raw."""


class WorkspaceError(ShimError):
    """A caller-supplied path cannot be served from inside the jail."""


class WorkspaceEscapeError(WorkspaceError):
    """An absolute path, a ``..`` escape, or a path outside the workspace root."""


class InvalidFilenameError(ShimError):
    """A module/export filename is not a plain basename (or not ``.py`` where required)."""


class UnsupportedFormatError(ShimError):
    """A binary-only export (STL in v1) was requested; STEP is the supported interchange."""


class UpstreamToolError(ShimError):
    """Upstream reported ``tool_error``, returned no result, or rejected our arguments.

    The message preserves upstream's own text: a bad script is the backend's
    message on the record, not a broken backend. That verbatim text may embed
    absolute server paths (venv, workspace root, OCC tracebacks) by design --
    an accepted disclosure (threat review V6), not a scrub target: callers
    are bearer-token holders, and scrubbing would break the verbatim-result
    contract and debug fidelity. What the shim itself raises (jail
    rejections, filename errors, unknown-tool) carries no absolute server
    paths -- only caller-supplied values.
    """


class UpstreamImportError(ShimError):
    """The upstream seam (``process_tool_request`` / ``tool_handlers``) could not be loaded."""
