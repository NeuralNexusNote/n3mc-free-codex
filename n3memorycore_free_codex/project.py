"""Choose the project label forwarded to the connected memory server."""
import os
import subprocess
from pathlib import Path


def detect_project(cwd=None):
    directory = cwd or os.getcwd()
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=directory,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            encoding="utf-8",
            check=True,
            timeout=2,
        )
        root = Path(result.stdout.rstrip("\r\n")).name
        if root:
            return root
    except (OSError, subprocess.SubprocessError, ValueError):
        pass
    return Path(os.path.abspath(directory)).name or None
