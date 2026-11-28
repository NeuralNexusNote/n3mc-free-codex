"""Resolve N3MemoryCore's data and child-process paths."""
import os
import sys
from pathlib import Path

_root = os.environ.get("N3MC_FREE_CODEX_HOME") or "~/.n3mc-free-codex"
HOME_DIR = os.path.abspath(os.path.expanduser(_root))
MEMORY_DIR = os.path.join(HOME_DIR, ".memory")
CONFIG_FILE = os.path.join(HOME_DIR, "config.json")
DB_PATH = os.path.join(MEMORY_DIR, "n3memory.db")
PID_FILE = os.path.join(MEMORY_DIR, "n3mc.pid")
AUDIT_LOG = os.path.join(MEMORY_DIR, "audit.log")
NOTICES_FILE = os.path.join(MEMORY_DIR, "notices.json")
SERVER_LOG = os.path.join(MEMORY_DIR, "server.log")
SERVER_START_FAILED_FILE = os.path.join(MEMORY_DIR, "server_start_failed")


def python_cmd():
    """Keep child processes isolated unless they need the source checkout to import."""
    command = [sys.executable]
    if sys.flags.isolated:
        return command + ["-I"]
    if sys.version_info >= (3, 11):
        try:
            in_checkout = Path.cwd() == Path(__file__).absolute().parents[1]
        except OSError:
            in_checkout = True
        if not in_checkout:
            command.append("-P")
    return command
