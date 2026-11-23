"""Path resolution for N3MemoryCore.

All persistent data lives under a single home directory, resolved at
import time from (in priority order):

1. $N3MC_HOME environment variable
2. ~/.n3mc/  (default)
"""
import os
import sys


def python_cmd() -> list[str]:
    """Preserve isolated mode, or keep unrelated working directories off sys.path."""
    command = [sys.executable]
    if sys.flags.isolated:
        command.append('-I')
    elif sys.version_info >= (3, 11):
        here = os.path.normcase(os.path.realpath(os.getcwd()))
        checkout = os.path.normcase(os.path.realpath(os.path.dirname(os.path.dirname(__file__))))
        if here != checkout:
            command.append('-P')
    return command


def get_home_dir() -> str:
    env = os.environ.get('N3MC_HOME')
    if env:
        return os.path.expanduser(env)
    return os.path.join(os.path.expanduser('~'), '.n3mc')


HOME_DIR     = get_home_dir()
MEMORY_DIR   = os.path.join(HOME_DIR,   '.memory')
DB_PATH      = os.path.join(MEMORY_DIR, 'n3memory.db')
PID_FILE     = os.path.join(MEMORY_DIR, 'n3mc.pid')
NOTICES_FILE = os.path.join(MEMORY_DIR, 'notices.json')
AUDIT_LOG    = os.path.join(MEMORY_DIR, 'audit.log')
# v1.5.0: stderr of the background server, and the marker written when the
# server exits during startup (spec §3 "Starting the server").
SERVER_LOG   = os.path.join(MEMORY_DIR, 'server.log')
SERVER_START_FAILED_MARKER = os.path.join(MEMORY_DIR, 'server_start_failed')
CONFIG_FILE  = os.path.join(HOME_DIR,   'config.json')
