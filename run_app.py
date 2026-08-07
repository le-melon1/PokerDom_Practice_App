#!/usr/bin/env python3
import os
import socket
import subprocess
import sys
from pathlib import Path


def lan_ip() -> str | None:
    """Best-effort local-network IP, so a phone on the same Wi-Fi knows what
    to type -- doesn't actually send anything, just asks the OS which local
    interface it would use to reach an external address."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except OSError:
        return None


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
    # 0.0.0.0 (not 127.0.0.1) so a phone on the same Wi-Fi can reach this --
    # single-user local app, no auth, so this is LAN-only exposure by
    # design, not intended to be reachable from the public internet.
    cmd = [python_executable, "-m", "uvicorn", "backend.api:app", "--host", "0.0.0.0", "--port", "8001"]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(project_root) + os.pathsep + env.get("PYTHONPATH", "")
    print(f"Starting app with: {' '.join(cmd)}")
    print("  on this computer:  http://127.0.0.1:8001/")
    ip = lan_ip()
    if ip:
        print(f"  on your phone (same Wi-Fi):  http://{ip}:8001/")
    try:
        subprocess.run(cmd, cwd=project_root, env=env, check=True)
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == "__main__":
    main()
