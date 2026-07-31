#!/usr/bin/env python3
import os
import subprocess
import sys
from pathlib import Path


def resolve_python_executable(project_root: Path | None = None) -> str:
    base = Path(project_root or Path(__file__).resolve().parent)
    candidates = [
        base / ".venv" / "bin" / "python3",
        base / ".venv" / "Scripts" / "python.exe",
        base / "venv" / "bin" / "python3",
        base / "venv" / "Scripts" / "python.exe",
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return sys.executable


def main() -> int:
    project_root = Path(__file__).resolve().parent
    python_executable = resolve_python_executable(project_root)
    cmd = [python_executable, "-m", "uvicorn", "backend.api:app", "--host", "127.0.0.1", "--port", "8001"]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(project_root) + os.pathsep + env.get("PYTHONPATH", "")
    print(f"Starting app with: {' '.join(cmd)}")
    try:
        subprocess.run(cmd, cwd=project_root, env=env, check=True)
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == "__main__":
    main()
