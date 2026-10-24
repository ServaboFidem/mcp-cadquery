"""Workspace jail: every server-side path resolves under the workspace root.

The jail is string-first on purpose. The service runs on Windows but tests
(and future hosts) may not, so ``pathlib`` host semantics are never trusted
to enforce the rule: ``C:\\Windows\\x`` parses as one plain component on
POSIX. Both ``/`` and ``\\`` are separators, drive-absolute (``C:``),
UNC (``\\\\``), and POSIX-absolute (``/``) forms are rejected, and any
``..`` segment is rejected before the path ever touches the filesystem.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from .errors import InvalidFilenameError, UnsupportedFormatError, WorkspaceEscapeError

_DRIVE_ABSOLUTE = re.compile(r"^[A-Za-z]:(?:[\\/]|$)")
_EXPORTS_DIR = "exports"

#: Basenames a saved module must never take (V2 follow-up). A planted
#: ``os.py``/``sys.py``/``cadquery.py`` would shadow that import in every
#: later script execution; whether the shadow wins depends on upstream's
#: ``sys.path`` order (UNVERIFIED-UPSTREAM), so the shim blocks the names
#: regardless of the order. Compared case-insensitively: Windows imports
#: are case-insensitive, so ``OS.PY`` shadows just as well as ``os.py``.
_RESERVED_MODULE_BASENAMES = frozenset({"os.py", "sys.py", "cadquery.py"})


def _split_segments(value: str) -> list[str]:
    return re.split(r"[\\/]+", value)


def _is_absolute_form(value: str) -> bool:
    return (
        value.startswith("/")
        or value.startswith("\\")
        or _DRIVE_ABSOLUTE.match(value) is not None
    )


def resolve_under(root: Path, value: str) -> Path:
    """Resolve ``value`` under ``root``; raise :class:`WorkspaceEscapeError` otherwise.

    Relative values (no ``..`` segment) join onto the root. Absolute values of
    any flavor are resolved as given -- which accepts ``<root>\\...`` receipts
    and rejects everything outside -- so a previously returned receipt path
    re-validates on reuse. The final check is on the resolved path, so
    symlinks cannot escape either.
    """
    if not value or not value.strip():
        raise WorkspaceEscapeError("empty path is outside the workspace")
    segments = _split_segments(value)
    if any(seg == ".." for seg in segments):
        raise WorkspaceEscapeError(f"path escapes the workspace: {value!r}")
    resolved_root = root.resolve()
    if _is_absolute_form(value):
        candidate = Path(value).resolve()
    else:
        candidate = (
            root / Path(*[s for s in segments if s not in ("", ".")])
        ).resolve()
    try:
        candidate.relative_to(resolved_root)
    except ValueError:
        raise WorkspaceEscapeError(
            f"path is outside the workspace: {value!r}"
        ) from None
    return candidate


def resolve_call_workspace(root: Path, workspace_path: str | None) -> Path:
    """Jail a per-call ``workspace_path``: omitted means the root, otherwise under it."""
    if workspace_path is None or not str(workspace_path).strip():
        return root
    return resolve_under(root, str(workspace_path))


def check_module_filename(filename: str) -> str:
    """A saved module is a bare ``.py`` basename inside the workspace.

    Reserved stdlib/top-package basenames (``os.py``, ``sys.py``,
    ``cadquery.py``) are rejected: a planted one would shadow that import
    in later script executions.
    """
    if not filename or not isinstance(filename, str):
        raise InvalidFilenameError("module_filename must be a non-empty .py basename")
    if (
        "/" in filename
        or "\\" in filename
        or _DRIVE_ABSOLUTE.match(filename) is not None
    ):
        raise InvalidFilenameError(
            f"module_filename must be a bare filename: {filename!r}"
        )
    if filename in (".", "..") or not filename.endswith(".py") or filename == ".py":
        raise InvalidFilenameError(f"module_filename must be a .py file: {filename!r}")
    if filename.lower() in _RESERVED_MODULE_BASENAMES:
        raise InvalidFilenameError(
            f"module_filename must not shadow a stdlib/package module: {filename!r}"
        )
    return filename


def check_export_filename(filename: str) -> str:
    """An export target is a bare basename; directories/absolutes are rejected.

    Upstream honors absolute and directory-containing filenames verbatim, so
    the jail closes that before upstream ever sees the value.
    """
    if not filename or not isinstance(filename, str):
        raise InvalidFilenameError("filename must be a non-empty basename")
    if (
        "/" in filename
        or "\\" in filename
        or _DRIVE_ABSOLUTE.match(filename) is not None
    ):
        raise InvalidFilenameError(
            f"filename must be a bare basename under exports/: {filename!r}"
        )
    if filename in (".", ".."):
        raise InvalidFilenameError(f"filename must be a bare basename: {filename!r}")
    return filename


#: Export formats the shim serves. ``None`` means "let upstream infer from the
#: extension" (STEP for ``.step``/``.stp``, binary STL for ``.stl``).
_SUPPORTED_EXPORT_FORMATS = frozenset({"STEP", "STL"})


def check_export_format(format: str | None, filename: str | None = None) -> str:
    """Validate the requested export format; return the normalized form.

    STL crosses base64-encoded (binary bytes are not valid artifact text,
    but base64 is): the payload block of the result carries the encoding.
    Unknown explicit formats fail as ``isError``.
    """
    name = "" if format is None else str(format).strip().upper()
    if not name and filename is not None:
        lowered = filename.lower()
        if lowered.endswith(".stl"):
            return "STL"
        return "STEP"
    if name in _SUPPORTED_EXPORT_FORMATS:
        return name
    raise UnsupportedFormatError(
        f"unsupported export format {format!r}; supported: STEP, STL"
    )


def export_target_path(root: Path, filename: str) -> Path:
    """The server-side path an export is actually written to: ``<root>/exports/<basename>``."""
    return resolve_under(
        root, os.path.join(_EXPORTS_DIR, check_export_filename(filename))
    )
