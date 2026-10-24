"""Entry point: workspace preflight, OCC preflight, prod spawn shape, stderr logging."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from cadquery_dxl_mcp.__main__ import build_prod_spawn, main

TESTS_DIR = Path(__file__).resolve().parent
SRC_DIR = TESTS_DIR.parent / "src"


def test_missing_workspace_root_exits_nonzero_naming_it(tmp_path: Path, capsys):
    missing = tmp_path / "nope" / "workspace"
    with pytest.raises(SystemExit) as exc_info:
        main(["serve", "--workspace-dir", str(missing)])
    assert exc_info.value.code != 0
    _, err = capsys.readouterr()
    assert "workspace" in err.lower()


def test_nothing_written_to_stdout_on_startup_failure(tmp_path: Path, capsys):
    missing = tmp_path / "nope"
    with pytest.raises(SystemExit):
        main(["serve", "--workspace-dir", str(missing)])
    out, _ = capsys.readouterr()
    assert out == ""


def test_prod_spawn_shape_is_direct_python_never_uv_run(tmp_path: Path):
    argv = build_prod_spawn(
        python_exe="D:\\data\\mcps\\cadquery\\.venv\\Scripts\\python.exe",
        workspace_dir="D:\\data\\cadquery\\workspace",
        env_file="D:\\data\\cadquery\\cadquery.env",
    )
    assert argv == [
        "D:\\data\\mcps\\cadquery\\.venv\\Scripts\\python.exe",
        "-I",
        "-m",
        "cadquery_dxl_mcp",
        "serve",
        "--workspace-dir",
        "D:\\data\\cadquery\\workspace",
        "--env-file",
        "D:\\data\\cadquery\\cadquery.env",
    ]
    assert not any("uv" in part for part in argv)


def test_broken_occ_import_exits_nonzero_naming_cause(tmp_path: Path):
    """No cadquery importable anywhere: serve must exit non-zero, stderr names it."""
    import importlib.util

    if importlib.util.find_spec("cadquery") is not None:
        pytest.skip(
            "cadquery is installed here; the absence path needs an OCC-less env"
        )
    workspace = tmp_path / "ws"
    workspace.mkdir()
    env = dict(os.environ)
    env["PYTHONPATH"] = str(SRC_DIR)
    env["PYTHONUTF8"] = "1"
    # An empty dir on the path shadows nothing; cadquery is simply absent.
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "cadquery_dxl_mcp",
            "serve",
            "--workspace-dir",
            str(workspace),
        ],
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
    )
    assert proc.returncode != 0, proc.stdout
    assert proc.stdout == "", f"stdout must carry only MCP frames, got: {proc.stdout!r}"
    assert "cadquery" in proc.stderr.lower()


def test_production_serve_warns_to_stderr_when_hatch_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
):
    """V7e: a set hatch is visible in the service log, never on stdout."""
    from cadquery_dxl_mcp import upstream as upstream_mod

    monkeypatch.setenv(upstream_mod.UPSTREAM_SRC_ENV, str(tmp_path))
    missing = tmp_path / "nope" / "workspace"
    with pytest.raises(SystemExit) as exc_info:
        main(["serve", "--workspace-dir", str(missing)])
    assert exc_info.value.code != 0
    out, err = capsys.readouterr()
    assert out == ""
    assert upstream_mod.UPSTREAM_SRC_ENV in err
    assert "warning" in err.lower()


def test_production_serve_quiet_about_hatch_when_unset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
):
    """V7e: the production-clean path (hatch unset) logs no hatch warning."""
    from cadquery_dxl_mcp import upstream as upstream_mod

    monkeypatch.delenv(upstream_mod.UPSTREAM_SRC_ENV, raising=False)
    missing = tmp_path / "nope" / "workspace"
    with pytest.raises(SystemExit):
        main(["serve", "--workspace-dir", str(missing)])
    out, err = capsys.readouterr()
    assert out == ""
    assert upstream_mod.UPSTREAM_SRC_ENV not in err


def test_no_stdout_print_calls_in_shim_sources():
    """Stdout is the MCP channel: the shim must never print without file=sys.stderr."""
    pkg = TESTS_DIR.parent / "src" / "cadquery_dxl_mcp"
    offenders = []
    for path in sorted(pkg.glob("*.py")):
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if "print(" in line and "file=sys.stderr" not in line:
                offenders.append(f"{path.name}:{lineno}: {line.strip()}")
    assert offenders == []
