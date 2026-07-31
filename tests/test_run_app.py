from pathlib import Path

from run_app import resolve_python_executable


def test_resolve_python_executable_prefers_project_venv(tmp_path):
    project_root = tmp_path / "project"
    venv_bin = project_root / ".venv" / "bin"
    venv_bin.mkdir(parents=True)
    python_path = venv_bin / "python3"
    python_path.write_text("#!/bin/sh\n")

    resolved = resolve_python_executable(project_root)

    assert resolved == str(python_path)
