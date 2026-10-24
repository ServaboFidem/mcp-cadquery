"""Loader path fallback: the sibling tree exposes both import styles.

Upstream is a ``src``-layout tree whose modules ALSO use absolute
``src.mcp_cadquery_server.*`` imports (handlers.py), so the loader must put
BOTH ``<root>/src`` (top-level ``mcp_cadquery_server`` package) and ``<root>``
(the ``src`` namespace) on ``sys.path``. The service spawns with ``-I`` (no
CWD), so without this the backend exits with
``UpstreamImportError: ... No module named 'src'`` ~4 s after start.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from cadquery_dxl_mcp import upstream


def test_upstream_roots_returns_src_first_then_root():
    roots = upstream._upstream_roots()
    assert len(roots) == 2
    src_dir, root = (Path(entry) for entry in roots)
    assert src_dir.name == "src"
    assert src_dir.parent == root
    assert (src_dir / "mcp_cadquery_server").is_dir()


def test_upstream_roots_point_at_this_checkout():
    roots = upstream._upstream_roots()
    here = Path(upstream.__file__).resolve()
    assert Path(roots[1]) == here.parent.parent.parent


def test_deployed_workspace_python_returns_service_interpreter(tmp_path):
    assert upstream._deployed_workspace_python(str(tmp_path)) == sys.executable


def test_deployed_workspace_python_fails_closed_on_missing_dir(tmp_path):
    with pytest.raises(FileNotFoundError):
        upstream._deployed_workspace_python(str(tmp_path / "nope"))


def test_apply_deployed_runtime_rebinds_handlers_seam():
    handlers = SimpleNamespace(prepare_workspace_env=object())
    upstream._apply_deployed_runtime(handlers, None)
    assert handlers.prepare_workspace_env is upstream._deployed_workspace_python


def test_apply_deployed_runtime_leaves_hatch_tree_alone():
    sentinel = object()
    handlers = SimpleNamespace(prepare_workspace_env=sentinel)
    upstream._apply_deployed_runtime(handlers, "/fake/upstream")
    assert handlers.prepare_workspace_env is sentinel
