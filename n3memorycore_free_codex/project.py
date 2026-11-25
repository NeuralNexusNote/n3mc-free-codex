"""Derive the connected server project label from the hook working directory."""
import os
import subprocess


def detect_project(cwd=None):
    """Return the workspace name: the folder name of `git rev-parse --show-toplevel`,
    else the name of the working folder, else None."""
    cwd = cwd or os.getcwd()
    try:
        out = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=cwd,
                             capture_output=True, text=True, encoding="utf-8",
                             check=True, timeout=2.0).stdout.strip()
        if out:
            return os.path.basename(out) or None
    except Exception:
        pass
    return os.path.basename(os.path.abspath(cwd)) or None
