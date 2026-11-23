import sys
import os

# Keep checkout execution working and exclude unrelated working directories
# before importing the modules used by this entry point.
if __name__ == '__main__' and sys.path:
    here = os.path.normcase(os.path.realpath(os.getcwd()))
    checkout = os.path.normcase(os.path.realpath(os.path.dirname(os.path.dirname(__file__))))
    if here != checkout and os.path.normcase(os.path.realpath(sys.path[0])) == here:
        del sys.path[0]

# spec §3: reconfigure all streams to UTF-8 before any I/O (Windows cp932 guard)
for _s_name in ("stdin", "stdout", "stderr"):
    _s = getattr(sys, _s_name, None)
    if _s is not None and hasattr(_s, 'reconfigure'):
        try:
            _s.reconfigure(encoding='utf-8')
        except Exception:
            pass

import argparse
import hashlib
import json
import logging
import re
import shutil
import sqlite3
import subprocess
import tempfile
import threading
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Optional

from .paths import HOME_DIR, MEMORY_DIR, DB_PATH, PID_FILE, AUDIT_LOG, CONFIG_FILE, NOTICES_FILE
from .paths import SERVER_LOG, SERVER_START_FAILED_MARKER
from .paths import python_cmd
from .core.database import (
    get_connection, init_db, migrate_schema, insert_memory, insert_memory_once,
    check_exact_duplicate, search_vector, find_unindexed_memories,
    strip_fts_punctuation, serialize_vector,
    embedding_index_compatible,
)
from .core.processor import (
    embed_passage, cosine_sim_from_l2, hybrid_search,
    purify_text, render_memory_context,
)

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

_PKG_DIR = os.path.dirname(os.path.abspath(__file__))
_CODE_FILES = (
    os.path.join(_PKG_DIR, 'n3memory.py'),
    os.path.join(_PKG_DIR, 'core', 'database.py'),
    os.path.join(_PKG_DIR, 'core', 'processor.py'),
    os.path.join(_PKG_DIR, 'maintenance.py'),
)

# Set by ensure_server() when the port answers with another folder's server
# (spec §3 "When the port belongs to another folder's server"). None = not foreign.
_FOREIGN_SERVER_ROOT: Optional[str] = None

# spec §4.5: inputs that are not typed by the user — no search, no save,
# no new turn_id.
_SYSTEM_PROMPT_PREFIXES = (
    '<task-notification>',
    '<agent-message from=',     # a subagent's report (2026-11-17)
    '<system-reminder>',        # an app notice (2026-11-17)
)

_HEADING = "# Recalled Memory Context"

# spec §3 Session ID fallback for direct (non-HTTP) writes from this CLI
# process: N3MC_SESSION_ID, else a per-process UUIDv4.
_CLI_SESSION_ID = os.environ.get('N3MC_SESSION_ID') or str(uuid.uuid4())

_FATAL_SAVE_MSG = "⚠️ Physical save failed. Current memories may be lost."
_SAVE_FAILED_MSG = ("A record could not be saved ({error}). Current memories may be lost; "
                    "if it happens again, check that no other program holds the memory database.")


def _norm(path: str) -> str:
    return os.path.normcase(os.path.abspath(os.path.expanduser(path)))


def _atomic_write_text(path: str, text: str) -> None:
    """spec §3.5 (v1.5.0): write a temporary file in the same folder, then
    os.replace it over the target — an interrupted write never leaves a
    truncated file."""
    folder = os.path.dirname(os.path.abspath(path))
    os.makedirs(folder, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=folder, prefix='.' + os.path.basename(path) + '.')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


# ---------------------------------------------------------------------------
# Audit log + notices (spec §3 "Notices")
# ---------------------------------------------------------------------------

def _append_audit(record: dict) -> None:
    try:
        os.makedirs(os.path.dirname(AUDIT_LOG), exist_ok=True)
        rec = {'ts': datetime.now(timezone.utc).isoformat()}
        rec.update(record)
        with open(AUDIT_LOG, 'a', encoding='utf-8') as f:
            f.write(json.dumps(rec, ensure_ascii=False) + '\n')
    except Exception as e:
        print(f"Warning: audit log write failed: {e}", file=sys.stderr)


def _load_notices() -> dict:
    try:
        with open(NOTICES_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_notices(notices: dict) -> None:
    try:
        os.makedirs(os.path.dirname(NOTICES_FILE), exist_ok=True)
        if not notices:
            if os.path.exists(NOTICES_FILE):
                os.remove(NOTICES_FILE)
            return
        # spec §3 "Notices" (v1.5.0): atomic, like config.json
        _atomic_write_text(NOTICES_FILE, json.dumps(notices, ensure_ascii=False, indent=2))
    except Exception as e:
        print(f"Warning: notices write failed: {e}", file=sys.stderr)


def _notify(key: str, message: str) -> None:
    """A notice that needs a human: stderr + audit.log (once per text) +
    notices.json (shown at the top of search output once a day)."""
    print(f"N3MC: {message}", file=sys.stderr)
    notices = _load_notices()
    prev = notices.get(key)
    if prev and prev.get('message') == message:
        return
    _append_audit({'hook': 'notice', 'key': key, 'message': message})
    notices[key] = {'message': message, 'last_shown': None}
    _save_notices(notices)


def _clear_notice(key: str) -> None:
    notices = _load_notices()
    if key in notices:
        del notices[key]
        _save_notices(notices)


def _take_notices() -> list:
    """Notices due for display (not shown in the last 24 h)."""
    notices = _load_notices()
    if not notices:
        return []
    now = time.time()
    due = []
    for v in notices.values():
        last = v.get('last_shown')
        if not last or now - float(last) >= 86400:
            due.append(v.get('message', ''))
            v['last_shown'] = now
    if due:
        _save_notices(notices)
    return due


def _status_md(body: str) -> str:
    """Heading + due notices + body (used for every non-result output).

    Without notices this is exactly "# Recalled Memory Context\\n\\n<body>\\n"
    (spec §5.4 degraded-state placeholders)."""
    parts = [_HEADING, ""]
    for n in _take_notices():
        parts += [f"> ⚠️ N3MC notice: {n}", ""]
    parts.append(body)
    return "\n".join(parts) + "\n"


def _emit(text: str) -> None:
    """Write search output to stdout as-is (stdout only; no file)."""
    sys.stdout.write(text if text.endswith("\n") else text + "\n")
    sys.stdout.flush()


# ---------------------------------------------------------------------------
# Config (spec §3 identifiers, §3.5)
# ---------------------------------------------------------------------------

_DEFAULT_CONFIG: dict = {
    "owner_id":                 None,
    "local_id":                 None,
    "bind_host":                "127.0.0.1",  # keep 127.0.0.1: the API has no auth
    "server_port":              18520,
    "embed_model":              "intfloat/multilingual-e5-base",
    "half_life_days":           90,
    "bm25_min_threshold":       0.1,
    "search_result_limit":      20,
    "min_score":                0.2,
    "search_query_max_chars":   2000,
    "vector_min_cos":           0.85,   # measured with multilingual-e5-base
    "relative_min_score_ratio": 0.6,
    "min_results":              0,      # no forced weak matches by default
    "semantic_rescue_enabled":  True,
    "semantic_rescue_min_cos":  0.80,
    "semantic_rescue_margin":   0.02,
    "context_max_chars":        12000,
    "pair_top_n":               3,
    "pair_max_chars":           3000,
    "version_order_enabled":    True,
    "version_sim_threshold":    0.98,   # measured with multilingual-e5-base
    "version_min_chars":        100,
    "reply_sim_rerank_enabled": False,  # spec §5 step 1b (2026-11-17)
    "reply_sim_alpha":          0.3,
    "reply_sim_floor":          0.80,   # measured with multilingual-e5-base
    "reply_sim_span":           0.15,   # measured with multilingual-e5-base
}


# spec §3.5 "Allowed values" (v1.5.0): (kind, min, max, min_exclusive)
# kind 'int' = JSON integer only (2000.0 is rejected); 'num' = int or float.
_CONFIG_RULES: dict = {
    'server_port':              ('int', 1, 65535, False),
    # C-06: the vector search uses k = 3 x limit; sqlite-vec refuses k > 4096.
    'search_result_limit':      ('int', 1, 1365, False),
    'pair_top_n':               ('int', 1, None, False),
    'pair_max_chars':           ('int', 1, None, False),
    'search_query_max_chars':   ('int', 1, None, False),
    'version_min_chars':        ('int', 1, None, False),
    'min_results':              ('int', 0, None, False),
    'semantic_rescue_min_cos':  ('num', 0, 1, False),
    'semantic_rescue_margin':   ('num', 0, 1, False),
    'context_max_chars':        ('int', 1000, 100000, False),
    'half_life_days':           ('num', 0, None, True),
    'bm25_min_threshold':       ('num', 0, None, False),
    'min_score':                ('num', 0, 1, False),
    'vector_min_cos':           ('num', 0, 1, False),
    'relative_min_score_ratio': ('num', 0, 1, False),
    'version_sim_threshold':    ('num', 0, 1, False),
    'reply_sim_alpha':          ('num', 0, 1, False),
    'reply_sim_floor':          ('num', 0, 1, False),
    'reply_sim_span':           ('num', 0, None, True),
}


def _config_value_ok(key: str, value) -> bool:
    """spec §3.5 (v1.5.0): type and range check of one config.json value."""
    if key not in _DEFAULT_CONFIG:
        return True
    default = _DEFAULT_CONFIG[key]
    if default is None:
        return True
    if isinstance(default, bool):
        return isinstance(value, bool)
    if isinstance(default, str):
        return isinstance(value, str)
    if isinstance(default, (int, float)):
        if isinstance(value, bool):
            return False                      # booleans are never numbers
        rule = _CONFIG_RULES.get(key)
        if rule is None:
            return isinstance(value, (int, float))
        kind, lo, hi, lo_exclusive = rule
        if kind == 'int':
            if not isinstance(value, int):
                return False
        elif not isinstance(value, (int, float)):
            return False
        if value != value:                    # NaN
            return False
        if lo is not None and (value <= lo if lo_exclusive else value < lo):
            return False
        if hi is not None and value > hi:
            return False
        return True
    return True


def _recover_ids_from_db(cfg: dict) -> None:
    """spec §3.5: recover owner_id / local_id from the most frequent DB value."""
    try:
        import sqlite3
        if not os.path.exists(DB_PATH):
            return
        conn = sqlite3.connect(DB_PATH)
        try:
            for col in ('owner_id', 'local_id'):
                if cfg.get(col):
                    continue
                row = conn.execute(
                    f"SELECT {col} FROM memories WHERE {col} IS NOT NULL "
                    f"GROUP BY {col} ORDER BY COUNT(*) DESC LIMIT 1"
                ).fetchone()
                if row and row[0]:
                    cfg[col] = row[0]
        finally:
            conn.close()
    except Exception:
        pass


def _fill_ids(cfg: dict) -> None:
    _recover_ids_from_db(cfg)
    for col in ('owner_id', 'local_id'):
        if not cfg.get(col):
            cfg[col] = str(uuid.uuid4())


def _read_config_file():
    """Parse config.json. A file that another process has just created may
    still be empty for a moment (exclusive creation, then write), so a
    very young file that does not parse is read again briefly."""
    for attempt in range(20):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if not isinstance(data, dict):
                raise ValueError("the top level is not a JSON object")
            return data
        except Exception:
            try:
                young = time.time() - os.path.getmtime(CONFIG_FILE) < 2.0
            except OSError:
                young = False
            if not young or attempt == 19:
                raise
            time.sleep(0.05)


def _create_config(cfg: dict) -> bool:
    """spec §3.5 (v1.5.0): create a missing config.json exclusively.
    False when another process created it first (read that file instead)."""
    os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
    try:
        f = open(CONFIG_FILE, 'x', encoding='utf-8')
    except FileExistsError:
        return False
    with f:
        f.write(json.dumps(cfg, indent=2, ensure_ascii=False))
        f.flush()
        os.fsync(f.fileno())
    return True


def _load_config() -> dict:
    """spec §3.5: never overwrite a config.json the user mistyped; create a
    missing one exclusively; update an existing one atomically."""
    os.makedirs(MEMORY_DIR, exist_ok=True)
    cfg = dict(_DEFAULT_CONFIG)

    if not os.path.exists(CONFIG_FILE):
        _fill_ids(cfg)
        if _create_config(cfg):
            return cfg
        cfg = dict(_DEFAULT_CONFIG)   # another process won: use its file

    try:
        data = _read_config_file()
    except Exception as e:
        _notify(
            'config_unreadable',
            f"config.json cannot be read ({e}). N3MC runs with default "
            f"settings until it is fixed; the file was NOT modified: {CONFIG_FILE}",
        )
        _fill_ids(cfg)   # this run only — not saved
        return cfg
    _clear_notice('config_unreadable')

    bad = []
    for k, v in data.items():
        if _config_value_ok(k, v):
            cfg[k] = v
        else:
            bad.append(k)
    if bad:
        _notify(
            'config_type',
            "config.json: these items have the wrong type or are out of range "
            f"and are ignored (defaults are used): {', '.join(sorted(bad))}. "
            "Write numbers without quotes, e.g. \"vector_min_cos\": 0.83, and "
            "counts as whole numbers without a decimal point, e.g. 2000.",
        )
    else:
        _clear_notice('config_type')

    for col in ('owner_id', 'local_id'):
        if not cfg.get(col):
            cfg[col] = None
    if not cfg.get('owner_id') or not cfg.get('local_id'):
        _fill_ids(cfg)

    missing = [k for k in _DEFAULT_CONFIG
               if k not in data or (data.get(k) is None and cfg.get(k) is not None)]
    if missing and not bad:
        merged = dict(data)
        for k in missing:
            merged[k] = cfg[k]
        _save_config(merged)
    return cfg


def _save_config(cfg: dict) -> None:
    """spec §3.5 (v1.5.0): temporary file in the same folder + os.replace."""
    _atomic_write_text(CONFIG_FILE, json.dumps(cfg, indent=2, ensure_ascii=False))


def _code_version() -> str:
    """spec §3: hash of the server code + config.json content (key order and
    whitespace do not matter)."""
    h = hashlib.sha256()
    for path in _CODE_FILES:
        try:
            with open(path, 'rb') as f:
                h.update(f.read())
        except Exception:
            h.update(path.encode('utf-8'))
    try:
        with open(CONFIG_FILE, 'rb') as f:
            raw = f.read()
    except Exception:
        raw = b''
    try:
        obj = json.loads(raw.decode('utf-8'))
        h.update(json.dumps(obj, sort_keys=True).encode('utf-8'))
    except Exception:
        h.update(raw)
    return h.hexdigest()[:16]


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def _local_open(req, timeout):
    """Open a request to this PC's own server, never through a proxy (spec §3 Communication, F16).

    urllib's default opener follows HTTP_PROXY / the system proxy settings; with a proxy and no
    NO_PROXY entry for 127.0.0.1 the request went to the proxy and the server looked down."""
    import urllib.request
    return urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=timeout)


def _post(cfg: dict, path: str, payload: dict, timeout: int = 30) -> dict:
    import urllib.request
    url = f"http://127.0.0.1:{cfg['server_port']}{path}"
    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(
        url, data=data,
        headers={'Content-Type': 'application/json',
                 'Host': f"127.0.0.1:{cfg['server_port']}"},   # spec §3 Host check
        method='POST',
    )
    with _local_open(req, timeout) as resp:
        return json.loads(resp.read().decode('utf-8'))


def _get(cfg: dict, path: str, timeout: int = 30) -> dict:
    import urllib.request
    url = f"http://127.0.0.1:{cfg['server_port']}{path}"
    req = urllib.request.Request(
        url, headers={'Host': f"127.0.0.1:{cfg['server_port']}"}, method='GET')
    with _local_open(req, timeout) as resp:
        return json.loads(resp.read().decode('utf-8'))


def _get_health(cfg: dict) -> Optional[dict]:
    try:
        r = _get(cfg, '/health', timeout=5)
        return r if isinstance(r, dict) and r.get('status') == 'ok' else None
    except Exception:
        return None


def _health_check(cfg: dict) -> bool:
    return _get_health(cfg) is not None


def _health_decision(health: Optional[dict]) -> str:
    """spec §3: 'none' | 'ok' | 'stale' | 'foreign' | 'legacy'."""
    if not health:
        return 'none'
    root = health.get('root')
    if not root:
        return 'legacy'
    if _norm(root) != _norm(HOME_DIR):
        return 'foreign'
    if health.get('code_version') != _code_version():
        return 'stale'
    return 'ok'


# ---------------------------------------------------------------------------
# Server management (spec §3 "Server check and replacement (ensure_server)")
# ---------------------------------------------------------------------------

def _process_alive(pid: int) -> bool:
    try:
        if sys.platform == 'win32':
            import ctypes
            SYNCHRONIZE = 0x100000
            handle = ctypes.windll.kernel32.OpenProcess(SYNCHRONIZE, False, pid)
            if not handle:
                return False
            ret = ctypes.windll.kernel32.WaitForSingleObject(handle, 0)
            ctypes.windll.kernel32.CloseHandle(handle)
            return ret == 0x102  # WAIT_TIMEOUT → still alive
        else:
            os.kill(pid, 0)
            return True
    except Exception:
        return False


def _is_own_server_process(pid: int) -> bool:
    """True only if psutil confirms pid is `n3memorycore.n3memory --run-server`
    whose data folder (N3MC_HOME) is ours."""
    try:
        import psutil
    except ImportError:
        return False
    if not pid:
        return False
    try:
        p = psutil.Process(int(pid))
        cmdline = ' '.join(p.cmdline())
        # spec §3: command line contains both markers
        if 'n3memorycore.n3memory' not in cmdline or '--run-server' not in cmdline:
            return False
        env = p.environ()
        home = env.get('N3MC_HOME')
        if home:
            their_home = home
        else:
            user_home = env.get('USERPROFILE') or env.get('HOME') or os.path.expanduser('~')
            their_home = os.path.join(user_home, '.n3mc')
        return _norm(their_home) == _norm(HOME_DIR)
    except Exception:
        # psutil missing / access denied / process gone → cannot verify
        return False


def _server_pid(cfg: dict, health: Optional[dict]) -> Optional[int]:
    """PID from /health's `pid`, else the process listening on the port."""
    pid = (health or {}).get('pid')
    if isinstance(pid, int) and not isinstance(pid, bool) and pid > 0:
        return pid
    return _listener_pid(cfg.get('server_port', 18520))


def _listener_pid(port: int) -> Optional[int]:
    try:
        import psutil
        for c in psutil.net_connections(kind='tcp'):
            if c.laddr and c.laddr.port == port and c.status == 'LISTEN' and c.pid:
                return c.pid
    except Exception:
        pass
    return None


def _request_shutdown(cfg: dict) -> bool:
    try:
        r = _post(cfg, '/shutdown', {'root': HOME_DIR}, timeout=5)
        return isinstance(r, dict) and r.get('status') == 'ok'
    except Exception:
        return False


def _wait_port_free(cfg: dict, max_wait: float = 15) -> bool:
    deadline = time.time() + max_wait
    while time.time() < deadline:
        if not _health_check(cfg):
            return True
        time.sleep(0.3)
    return False


def _stop_stale_server(cfg: dict, health: dict) -> bool:
    """Ask /shutdown first; for servers without it (v1.3.x) terminate only a
    process psutil confirms as ours. Never use the PID file's number."""
    if _request_shutdown(cfg):
        return _wait_port_free(cfg)

    pid = _server_pid(cfg, health)
    if pid and _is_own_server_process(pid):
        try:
            import psutil
            proc = psutil.Process(pid)
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except Exception:
                proc.kill()
        except Exception:
            pass
        # Remove the PID file only if it names the process we just stopped.
        try:
            with open(PID_FILE, 'r', encoding='utf-8') as f:
                same = f.read().strip() == str(pid)
            if same:
                os.remove(PID_FILE)
        except Exception:
            pass
        return _wait_port_free(cfg)

    _notify('stale_server', _STALE_SERVER_MSG)
    return False


_STALE_SERVER_MSG = (
    "Cannot stop the old server. Another N3MC folder may be using the same "
    "`server_port`. Check `server_port` in each folder's `config.json` and "
    "restart manually."
)


def _wait_for_server(cfg: dict, max_wait: int = 60, proc=None) -> bool:
    """Poll /health every 0.5 s. With `proc`, stop at once when the child
    process exits (spec §3 "Starting the server", step 2)."""
    deadline = time.time() + max_wait
    while time.time() < deadline:
        health = _get_health(cfg)
        if _health_decision(health) == 'ok':
            _adopt_server_pid(health)
            return True
        if proc is not None and proc.poll() is not None:
            return False
        time.sleep(0.5)
    return False


def _adopt_server_pid(health: dict) -> None:
    """Replace a Windows venv launcher's reservation with its serving child."""
    pid = health.get('pid')
    if type(pid) is not int or pid <= 0:
        return
    try:
        import psutil
    except ImportError:
        return
    try:
        with open(PID_FILE, encoding='utf-8') as file:
            reserved = int(file.read().strip())
        if reserved != pid and psutil.Process(pid).ppid() == reserved:
            _atomic_write_text(PID_FILE, str(pid))
    except (OSError, ValueError, psutil.Error):
        # No matching reservation, or the server exited during the check.
        return


# Why this command runs without the server (None = it may use the server).
# _do_buffer then saves directly and _do_search prints the reason.
_NO_SERVER_REASON: Optional[str] = None

_STILL_STARTING = 'the memory server is still starting'
_START_FAILED = 'the memory server could not start'

# spec §3 (v1.5.0)
_START_FAILED_BACKOFF_SECONDS = 300
_SERVER_LOG_MAX_BYTES = 1024 * 1024
_PID_FILE_GRACE_SECONDS = 60


def _server_answered() -> bool:
    """spec §3: once our own server responds, clear the server notices and
    the start-failure marker."""
    global _NO_SERVER_REASON
    _NO_SERVER_REASON = None
    _clear_notice('stale_server')
    _clear_notice('port_conflict')
    _clear_notice('server_start_failed')
    try:
        os.remove(SERVER_START_FAILED_MARKER)
    except OSError:
        pass
    return True


def _start_failed_recently() -> bool:
    """spec §3 step 4: a start failed less than 5 minutes ago."""
    if not os.path.exists(SERVER_START_FAILED_MARKER):
        return False
    try:
        with open(SERVER_START_FAILED_MARKER, 'r', encoding='utf-8') as f:
            t = float(f.read().strip())
    except Exception:
        try:
            t = os.path.getmtime(SERVER_START_FAILED_MARKER)
        except OSError:
            return False
    return time.time() - t < _START_FAILED_BACKOFF_SECONDS


def _open_server_log():
    """spec §3 step 1: stderr of the server -> .memory/server.log (append),
    truncated first when it is larger than 1 MB."""
    os.makedirs(os.path.dirname(SERVER_LOG), exist_ok=True)
    try:
        if os.path.getsize(SERVER_LOG) > _SERVER_LOG_MAX_BYTES:
            open(SERVER_LOG, 'wb').close()
    except OSError:
        pass
    return open(SERVER_LOG, 'ab')


def _detach_kwargs() -> dict:
    """spec §3 Clean CLI (v1.5.0): keep the server alive after the hook exits."""
    if os.name == 'nt':
        return {'creationflags': subprocess.CREATE_NEW_PROCESS_GROUP
                                 | subprocess.CREATE_NO_WINDOW}
    return {'start_new_session': True}


def _spawn_server():
    log = _open_server_log()
    try:
        return subprocess.Popen(
            [*python_cmd(), '-m', 'n3memorycore.n3memory', '--run-server'],
            stderr=log, stdout=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
            **_detach_kwargs(),
        )
    finally:
        log.close()   # the child keeps its own handle


def _record_start_failure(code) -> None:
    _notify(
        'server_start_failed',
        f"The N3MC memory server could not start (exit code {code}). "
        f"See {SERVER_LOG} for the reason.",
    )
    try:
        _atomic_write_text(SERVER_START_FAILED_MARKER, str(time.time()))
    except Exception as e:
        print(f"Warning: could not write {SERVER_START_FAILED_MARKER}: {e}",
              file=sys.stderr)


def _start_server(cfg: dict) -> bool:
    """spec §3 "Starting the server (_start_server, v1.5.0)"."""
    global _NO_SERVER_REASON
    if _start_failed_recently():
        _NO_SERVER_REASON = _START_FAILED + f" (see {SERVER_LOG})"
        return False
    # spec §3: atomic exclusive-create of the PID file prevents two CLIs from
    # launching two servers at the same time.
    try:
        pid_fh = open(PID_FILE, 'x', encoding='utf-8')
    except FileExistsError:
        # Another process is starting the server right now - wait for it.
        if _wait_for_server(cfg, max_wait=60):
            return _server_answered()
        _NO_SERVER_REASON = _STILL_STARTING
        return False
    try:
        proc = _spawn_server()
        pid_fh.write(str(proc.pid))
    except Exception as e:
        pid_fh.close()
        try:
            os.remove(PID_FILE)
        except Exception:
            pass
        # Never let a failed launch stop the hook: run without the server.
        print(f"Warning: could not launch the N3MC server: {e}", file=sys.stderr)
        _NO_SERVER_REASON = _START_FAILED + f" ({e})"
        return False
    pid_fh.close()
    if _wait_for_server(cfg, max_wait=60, proc=proc):
        return _server_answered()
    code = proc.poll()
    if code is not None:
        # Exited during startup: port held by another program, missing
        # dependency, DB cannot be opened, ...
        _record_start_failure(code)
        try:
            with open(PID_FILE, 'r', encoding='utf-8') as f:
                same = f.read().strip() == str(proc.pid)
            if same:
                os.remove(PID_FILE)
        except Exception:
            pass
        _NO_SERVER_REASON = _START_FAILED + f" (see {SERVER_LOG})"
        return False
    # Still alive after 60 s: the first start downloads the model. Leave it.
    _NO_SERVER_REASON = _STILL_STARTING
    return False


_LEGACY_FOREIGN_ROOT = '(unknown: the server did not report its folder)'


def _notify_port_conflict(cfg: dict, root: str) -> None:
    port = cfg.get('server_port', 18520)
    _notify(
        'port_conflict',
        f"Port {port} is used by the N3MC server of another folder ({root}). "
        "This folder does not use that server. "
        f"Set `server_port` in {CONFIG_FILE} to a free port to restore server-backed search.",
    )


def _psutil_available() -> bool:
    try:
        import psutil  # noqa: F401
        return True
    except ImportError:
        return False


def _pid_file_process_starting(pid: Optional[int]) -> bool:
    """Check the server process or honor a recent, still-empty reservation."""
    if pid is None or not _psutil_available():
        try:
            age = time.time() - os.path.getmtime(PID_FILE)
        except OSError:
            return False
        return age < _PID_FILE_GRACE_SECONDS
    return pid > 0 and _process_alive(pid) and _is_own_server_process(pid)


def ensure_server(cfg: dict) -> bool:
    """Return True when a server of this folder with the current code answers.

    False with _FOREIGN_SERVER_ROOT set: never send this command to that server.
    False with _NO_SERVER_REASON set: no server for this command.
    """
    global _FOREIGN_SERVER_ROOT, _NO_SERVER_REASON
    _FOREIGN_SERVER_ROOT = None
    _NO_SERVER_REASON = None
    os.makedirs(MEMORY_DIR, exist_ok=True)

    health = _get_health(cfg)
    decision = _health_decision(health)
    if decision == 'ok':
        _adopt_server_pid(health)
        return _server_answered()
    if decision == 'foreign':
        # Another folder's server: do not stop it, do not use it.
        _FOREIGN_SERVER_ROOT = health.get('root')
        _notify_port_conflict(cfg, _FOREIGN_SERVER_ROOT)
        return False
    if decision == 'legacy':
        # No `root` (v1.3.x or older): stop it only if psutil confirms it is
        # ours; otherwise treat it as another folder's server.
        if not _is_own_server_process(_server_pid(cfg, health)):
            _FOREIGN_SERVER_ROOT = _LEGACY_FOREIGN_ROOT
            _notify_port_conflict(cfg, _LEGACY_FOREIGN_ROOT)
            return False
        if not _stop_stale_server(cfg, health):
            _FOREIGN_SERVER_ROOT = _LEGACY_FOREIGN_ROOT
            return False
    elif decision == 'stale':
        # Same root, different code_version: stop it and restart.
        if not _stop_stale_server(cfg, health):
            # Could not stop it (notice `stale_server` emitted). It serves our
            # own DB, so keep using it until a human restarts it.
            return True

    # No server answers. spec §3 "PID file handling"
    if os.path.exists(PID_FILE):
        pid = None
        try:
            with open(PID_FILE, 'r', encoding='utf-8') as f:
                pid = int(f.read().strip())
        except Exception:
            pid = None
        if _pid_file_process_starting(pid):
            # This folder's server is starting up: keep the PID file and wait.
            if _wait_for_server(cfg, max_wait=60):
                return _server_answered()
            # Still starting after 60 s: no second server, keep the PID file.
            _NO_SERVER_REASON = _STILL_STARTING
            return False
        # Dead / reused PID: delete without waiting.
        try:
            os.remove(PID_FILE)
        except Exception:
            pass

    return _start_server(cfg)


# ---------------------------------------------------------------------------
# Direct buffer fallback (no embedding — used when server is down/foreign)
# ---------------------------------------------------------------------------

def _is_corruption_error(e: BaseException) -> bool:
    """spec §3.5 (F13): the DatabaseError of a damaged file — "file is not a
    database" or "database disk image is malformed". Not OperationalError
    (e.g. "database is locked") and not the sqlite-vec load failure."""
    if not isinstance(e, sqlite3.DatabaseError) or isinstance(e, sqlite3.OperationalError):
        return False
    msg = str(e).lower()
    return 'file is not a database' in msg or 'malformed' in msg


def _connect_checked(pragma: Optional[str]):
    """spec §3.5: open DB_PATH and run `PRAGMA <pragma>` (quick_check /
    integrity_check; None = no check). A DB that fails the check — a result
    other than 'ok', or (F13) a corruption error raised by opening it or by
    the check itself — is set aside (_handle_corrupt_db) and a new empty DB
    is opened. Any other error is raised unchanged."""
    try:
        conn = get_connection(DB_PATH)
    except sqlite3.DatabaseError as e:
        if not _is_corruption_error(e):
            raise
        _handle_corrupt_db()
        return get_connection(DB_PATH)
    if pragma is None:
        return conn
    try:
        result = conn.execute(f"PRAGMA {pragma}").fetchone()
    except sqlite3.DatabaseError as e:
        conn.close()
        if not _is_corruption_error(e):
            raise
        _handle_corrupt_db()
        return get_connection(DB_PATH)
    if result and result[0] != 'ok':
        conn.close()
        _handle_corrupt_db()
        return get_connection(DB_PATH)
    return conn


def _quick_check_once():
    """spec §3.5 (v1.5.0): PRAGMA quick_check at most once per process
    (the direct-save path). Returns an open connection."""
    global _QUICK_CHECK_DONE
    pragma = None if _QUICK_CHECK_DONE else 'quick_check'
    _QUICK_CHECK_DONE = True
    return _connect_checked(pragma)


# Set once quick_check has run in this process (spec §3.5, v1.5.0).
_QUICK_CHECK_DONE = False


def _buffer_direct(
    content: str,
    cfg: dict,
    agent_name: Optional[str] = None,
    session_id: Optional[str] = None,
    turn_id: Optional[str] = None,
) -> None:
    from .core.database import count_memories
    from uuid_extensions import uuid7

    content = purify_text(content) if content else content
    if not content or not content.strip():
        return

    # spec §3.5: quick_check in the fallback path (lighter than
    # integrity_check), once per process
    conn = _quick_check_once()
    try:
        init_db(conn)
        migrate_schema(conn)
        # spec §5.4: exact text only (same turn_id when given) — same rule as /buffer
        if check_exact_duplicate(conn, content, turn_id=turn_id):
            return

        before = count_memories(conn)
        ts = datetime.now(timezone.utc).isoformat()
        rowid = insert_memory_once(
            conn, str(uuid7()), content, ts,
            owner_id=cfg['owner_id'],
            local_id=cfg.get('local_id'),
            agent_name=agent_name,
            session_id=session_id or _CLI_SESSION_ID,
            turn_id=turn_id,
        )
        if rowid is None:
            return                      # spec §5.4 (R04): saved meanwhile
        if count_memories(conn) == before:
            raise RuntimeError("record count did not change after INSERT")
    finally:
        conn.close()


def _corrupt_backup_path() -> str:
    """n3memory.db.corrupt-<YYYYmmddHHMMSS>.bak (local time). A second
    corruption within the same second gets a -<n> suffix before .bak."""
    stamp = datetime.now().strftime('%Y%m%d%H%M%S')
    path = f"{DB_PATH}.corrupt-{stamp}.bak"
    n = 1
    while any(os.path.exists(path + sfx) for sfx in ('', '-wal', '-shm')):
        n += 1
        path = f"{DB_PATH}.corrupt-{stamp}-{n}.bak"
    return path


def _handle_corrupt_db() -> str:
    """spec §3.5 (v1.5.0): set the DB aside under a timestamped name and
    MOVE its -wal / -shm next to it (never delete them), then notify."""
    corrupt = _corrupt_backup_path()
    for src, dst in ((DB_PATH, corrupt),
                     (DB_PATH + '-wal', corrupt + '-wal'),
                     (DB_PATH + '-shm', corrupt + '-shm')):
        if os.path.exists(src):
            try:
                shutil.move(src, dst)
            except Exception as e:
                print(f"Warning: could not move {src} to {dst}: {e}", file=sys.stderr)
    print(
        f"Warning: DB corruption detected. Set aside as {corrupt} (with its "
        "-wal / -shm). A new empty DB will be created. Recovery: rename the "
        "sidecars back to <name>-wal / <name>-shm if needed, then "
        f"`sqlite3 {corrupt} .recover | sqlite3 recovered.db`.",
        file=sys.stderr,
    )
    _notify(
        'db_corrupt',
        f"The memory DB failed its integrity check and was set aside as {corrupt}. "
        "A new empty DB is in use. To recover records: "
        f"sqlite3 {corrupt} .recover | sqlite3 recovered.db",
    )
    return corrupt


# ---------------------------------------------------------------------------
# Time bounds for --since / --until (spec §3.6, v1.5.0)
# ---------------------------------------------------------------------------

# None = the machine's local time zone. Tests set a fixed tzinfo.
_LOCAL_TZ = None

_DATE_ONLY_RE = re.compile(r'^\d{4}-\d{2}-\d{2}$')
_DATETIME_RE = re.compile(
    r'^(\d{4}-\d{2}-\d{2})[Tt ](\d{2}:\d{2}(?::\d{2}(?:\.\d{1,6})?)?)'
    r'(Z|z|[+-]\d{2}:?\d{2})?$'
)


class TimeBoundError(ValueError):
    pass


def _local_aware(dt: datetime) -> datetime:
    if _LOCAL_TZ is not None:
        return dt.replace(tzinfo=_LOCAL_TZ)
    return dt.astimezone()     # naive → the machine's local time (DST aware)


def _parse_time_bound(value: Optional[str], is_until: bool = False,
                      name: Optional[str] = None) -> Optional[str]:
    """spec §3.6 (v1.5.0): date or ISO datetime (T or space, optional
    offset/Z) → UTC string formatted like the stored timestamps.
    Offset-less values are local time; a date-only until is 23:59:59.999999.
    Raises TimeBoundError on unreadable input."""
    if value is None:
        return None
    v = str(value).strip()
    if not v:
        return None
    label = name or ('--until' if is_until else '--since')
    try:
        if _DATE_ONLY_RE.match(v):
            d = datetime.strptime(v, '%Y-%m-%d')
            if is_until:
                d = d.replace(hour=23, minute=59, second=59, microsecond=999999)
            dt = _local_aware(d)
        else:
            m = _DATETIME_RE.match(v)
            if not m:
                raise ValueError(v)
            date_part, time_part, off = m.groups()
            text = f"{date_part}T{time_part}"
            if off:
                if off in ('Z', 'z'):
                    off = '+00:00'
                elif ':' not in off:
                    off = off[:3] + ':' + off[3:]
                text += off
            dt = datetime.fromisoformat(text)
            dt = _local_aware(dt) if dt.tzinfo is None else dt
    except Exception:
        raise TimeBoundError(
            f"{label}: cannot read '{value}' (use 2026-11-13 or 2026-11-13T09:00)"
        ) from None
    return dt.astimezone(timezone.utc).isoformat()


def _parse_time_range(since: Optional[str], until: Optional[str]):
    """Both bounds; TimeBoundError when unreadable or since > until."""
    s = _parse_time_bound(since, is_until=False)
    u = _parse_time_bound(until, is_until=True)
    if s and u and datetime.fromisoformat(s) > datetime.fromisoformat(u):
        raise TimeBoundError('--since is later than --until')
    return s, u


# ---------------------------------------------------------------------------
# FastAPI application
# ---------------------------------------------------------------------------

def _exit_server_process() -> None:
    try:
        with open(PID_FILE, 'r') as f:
            if f.read().strip() == str(os.getpid()):
                f.close()
                os.remove(PID_FILE)
    except Exception:
        pass
    os._exit(0)


def _check_host(host: Optional[str]) -> bool:
    """spec §3 (v1.5.0): only Host 127.0.0.1:<port> or localhost:<port>."""
    port = (_srv_cfg or {}).get('server_port') or _DEFAULT_CONFIG['server_port']
    h = (host or '').strip().lower()
    return h in (f'127.0.0.1:{port}', f'localhost:{port}')


# Looked up at request time so tests can replace the check (TestClient sends
# Host: testserver).
_host_ok = _check_host

# Global server state (populated in lifespan)
_srv_cfg: dict = {}
_srv_session: str = ""
_srv_code_version: str = ""

# spec §3.5 (v1.5.0): one /repair batch per prompt-hook turn
_HOOK_REPAIR_MAX_RECORDS = 200


_EMBED_MISMATCH_MSG = (
    "The stored vectors were made with {recorded}, but config.json sets embed_model to "
    "{configured}. Search quality is degraded until they are re-made: run n3mc --reembed "
    "(it re-embeds all {n} records with {configured}), or set embed_model back to {recorded}."
)


def _record_embed_model(conn, model: str) -> None:
    from .core.database import meta_set, vec_table_dim
    meta_set(conn, 'embed_model', model)
    meta_set(conn, 'embed_dim', str(vec_table_dim(conn) or ''))
    meta_set(conn, 'embed_model_at', datetime.now(timezone.utc).isoformat(timespec='seconds'))


def _check_embed_model(conn, current_model: str) -> None:
    """spec §3.5: fill meta.embed_model once, then compare it with the configured model."""
    from .core.database import meta_get
    recorded = meta_get(conn, 'embed_model')
    if recorded is None:
        has_vectors = conn.execute("SELECT 1 FROM memories_vec LIMIT 1").fetchone() is not None
        recorded = current_model
        legacy = os.path.join(MEMORY_DIR, 'vec_model.txt')
        if has_vectors and os.path.exists(legacy):
            try:
                with open(legacy, 'r', encoding='utf-8') as f:
                    recorded = f.read().strip() or current_model
            except OSError:
                recorded = current_model
        _record_embed_model(conn, recorded)
        conn.commit()
    if recorded != current_model:
        n = conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
        _notify('embed_model_mismatch', _EMBED_MISMATCH_MSG.format(
            recorded=recorded, configured=current_model, n=n))
    else:
        _clear_notice('embed_model_mismatch')


def cmd_reembed(cfg: dict) -> int:
    """spec §3.5 `--reembed`: re-embed every record with the configured model, in this
    process, in resumable batches of 200. Returns the exit status."""
    from .core.database import (get_connection, init_db, migrate_schema, meta_get, meta_set,
                                meta_delete, serialize_vector, vec_table_dim)
    from .core.processor import get_model
    model_name = cfg.get('embed_model') or _DEFAULT_CONFIG['embed_model']
    _request_shutdown(cfg)          # this folder's server only; restarted by the next CLI call
    try:
        model = get_model(model_name)
        probe = model.encode("passage: probe", normalize_embeddings=True)
    except Exception as e:
        print(f"N3MC: --reembed: the model {model_name} could not be loaded: {e}", file=sys.stderr)
        return 1
    conn = get_connection(DB_PATH)
    try:
        init_db(conn)
        migrate_schema(conn)
        table_dim = vec_table_dim(conn)
        if table_dim is not None and len(probe) != table_dim:
            print(f"N3MC: --reembed: {model_name} makes {len(probe)}-dimensional vectors but "
                  f"memories_vec has {table_dim}; a different dimension needs the manual procedure "
                  "in \u00a73 \"Embeddings\".", file=sys.stderr)
            return 1
        cursor = -1
        if meta_get(conn, 'reembed_model') == model_name:
            try:
                cursor = int(meta_get(conn, 'reembed_cursor') or -1)
            except ValueError:
                cursor = -1
        else:
            meta_set(conn, 'reembed_model', model_name)
            meta_delete(conn, 'reembed_cursor')
            conn.commit()
        total = conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
        done = conn.execute("SELECT COUNT(*) FROM memories WHERE rowid <= ?", (cursor,)).fetchone()[0]
        while True:
            rows = conn.execute("SELECT rowid, content, id FROM memories WHERE rowid > ? "
                                "ORDER BY rowid LIMIT 200", (cursor,)).fetchall()
            if not rows:
                break
            try:
                vecs = model.encode(["passage: " + r[1] for r in rows], normalize_embeddings=True)
                if len(vecs) != len(rows) or any(len(vec) != len(probe) for vec in vecs):
                    raise ValueError('model returned an incomplete or wrong-dimension batch')
            except Exception as e:
                print(f"N3MC: --reembed: batch after rowid {cursor} failed: {e}", file=sys.stderr)
                return 1
            ids = [r[0] for r in rows]
            conn.execute('BEGIN IMMEDIATE')
            live = [(row[0], vec) for row, vec in zip(rows, vecs)
                    if conn.execute('SELECT 1 FROM memories WHERE rowid = ? AND id = ?',
                                    (row[0], row[2])).fetchone()]
            conn.executemany("DELETE FROM memories_vec WHERE rowid = ?", [(i,) for i, _ in live])
            conn.executemany("INSERT INTO memories_vec(rowid, embedding) VALUES (?, ?)",
                             [(i, serialize_vector(list(v))) for i, v in live])
            cursor = ids[-1]
            meta_set(conn, 'reembed_cursor', str(cursor))
            conn.commit()
            done += len(rows)
            print(f"Re-embedded {done} / {total}", file=sys.stderr)
        _record_embed_model(conn, model_name)
        meta_delete(conn, 'reembed_model')
        meta_delete(conn, 'reembed_cursor')
        conn.commit()
    finally:
        conn.close()
    _clear_notice('embed_model_mismatch')
    print(f"Re-embedded {done} record(s) with {model_name}.", file=sys.stderr)
    return 0


def _repair_db(max_records: Optional[int] = None) -> int:
    """Body of /repair. max_records limits the records changed in this call
    (FTS punctuation cleaning and index repair); None = everything."""
    from .core.database import (
        get_connection, find_unindexed_memories, serialize_vector,
        strip_fts_punctuation, bigram_text, fill_bigram_index,
        init_db, meta_delete, meta_get, meta_set, vec_table_dim,
    )
    from .core.processor import embed_passage

    budget = max_records if (isinstance(max_records, int) and max_records > 0) else None

    def left() -> Optional[int]:
        return None if budget is None else budget - repaired

    conn = get_connection(DB_PATH)
    repaired = 0
    try:
        init_db(conn)   # spec §3.5 (v1.8.0): the meta table of an older DB
        # spec §3: FTS punct cleaning — one-time migration; key in the meta
        # table (v1.8.0: was the file .memory/fts_punct_cleaned)
        while meta_get(conn, 'fts_punct_cleaned') != '1' and (left() is None or left() > 0):
            # Take the lock before reading the cursor. Concurrent repair
            # requests must resume from the latest committed page.
            with conn:
                conn.execute('BEGIN IMMEDIATE')
                if meta_get(conn, 'fts_punct_cleaned') == '1':
                    break
                try:
                    cursor = int(meta_get(conn, 'fts_punct_cursor') or -1)
                except ValueError:
                    cursor = -1
                rows = conn.execute(
                    "SELECT rowid, content FROM memories_fts WHERE rowid > ? "
                    "ORDER BY rowid LIMIT 200", (cursor,)
                ).fetchall()
                processed = 0
                for rowid, content in rows:
                    if left() is not None and left() <= 0:
                        break
                    clean = strip_fts_punctuation(content)
                    if clean != content:
                        conn.execute("UPDATE memories_fts SET content = ? WHERE rowid = ?",
                                     (clean, rowid))
                        repaired += 1
                    cursor = rowid
                    processed += 1
                if processed == len(rows) and len(rows) < 200:
                    meta_set(conn, 'fts_punct_cleaned', '1')
                    meta_delete(conn, 'fts_punct_cursor')
                else:
                    meta_set(conn, 'fts_punct_cursor', str(cursor))
        if repaired:
            print(f"FTS punctuation cleaned: {repaired} record(s).", file=sys.stderr)

        # spec §3 (2026-11-17): one-time CJK bigram index of the records
        # saved before memories_fts_bi existed. New records are indexed by
        # insert_memory, so later calls skip this. Not limited by
        # max_records: it embeds nothing (about 5 s for 18,000 records).
        if meta_get(conn, 'fts_bigram') != '1':
            n_bi = fill_bigram_index(conn)
            meta_set(conn, 'fts_bigram', '1')
            conn.commit()
            if n_bi > 0:
                print(f"FTS bigram index: {n_bi} record(s).", file=sys.stderr)

        # spec §3.5 "Index metadata" (v1.8.0): the model that made the
        # stored vectors, recorded in the DB; a mismatch is a notice.
        current_model = (_srv_cfg or {}).get('embed_model', 'intfloat/multilingual-e5-base')
        _check_embed_model(conn, current_model)

        # spec §3.5: batch 200 at a time; OFFSET always 0 (repaired records
        # disappear from WHERE clause automatically)
        while True:
            remaining = left()
            if remaining is not None and remaining <= 0:
                break
            batch = 200 if remaining is None else min(200, remaining)
            rows = find_unindexed_memories(conn, limit=batch)  # OFFSET=0 always
            if not rows:
                break
            batch_repaired = 0
            # spec §3.5 (F11): every embedding of the batch is computed first,
            # outside any transaction; only then are the rows written and
            # committed. Until then the first INSERT opened the write
            # transaction and it stayed open while the rest of the batch was
            # embedded, so a /buffer that came meanwhile waited for the busy
            # timeout and failed with "database is locked".
            if conn.in_transaction:
                conn.commit()
            vecs = {}
            for row in rows:
                if row['vec_rowid'] is None and embedding_index_compatible(conn, current_model):
                    try:
                        vecs[row['rowid']] = embed_passage(row['content'])
                    except Exception as e:
                        logger.warning(f"Repair embed rowid={row['rowid']}: {e}")
            conn.execute('BEGIN IMMEDIATE')
            for row in rows:
                rowid    = row['rowid']
                content  = row['content']
                # A concurrent forget can remove/reuse rowids while embedding.
                # Hold the write lock, then verify identity before index writes.
                live = conn.execute('SELECT id FROM memories WHERE rowid = ?', (rowid,)).fetchone()
                if not live or live['id'] != row['id']:
                    continue
                changed  = False

                if (rowid in vecs and embedding_index_compatible(conn, current_model)
                        and not conn.execute("SELECT 1 FROM memories_vec WHERE rowid = ?", (rowid,)).fetchone()):
                    conn.execute(
                        "INSERT INTO memories_vec(rowid, embedding) VALUES (?, ?)",
                        (rowid, serialize_vector(vecs[rowid]))
                    )
                    batch_repaired += 1
                    changed = True

                if (row['fts_rowid'] is None
                        and not conn.execute("SELECT 1 FROM memories_fts WHERE rowid = ?", (rowid,)).fetchone()):
                    stripped = strip_fts_punctuation(content)
                    conn.execute(
                        "INSERT INTO memories_fts(rowid, content) VALUES (?, ?)",
                        (rowid, stripped)
                    )
                    batch_repaired += 1
                    changed = True

                # Repair each index independently, even after its initial migration.
                if (row['bigram_rowid'] is None
                        and not conn.execute("SELECT 1 FROM memories_fts_bi WHERE rowid = ?", (rowid,)).fetchone()):
                    conn.execute(
                        "INSERT INTO memories_fts_bi(rowid, content) VALUES (?, ?)",
                        (rowid, bigram_text(content))
                    )
                    batch_repaired += 1
                    changed = True

                # spec §4 (2026-11-16): count only records this call changed
                if changed:
                    repaired += 1

            conn.commit()
            # spec §3.5: exit if no progress (e.g. embed model unavailable)
            if batch_repaired == 0:
                break
            if len(rows) < batch:
                break
    finally:
        conn.close()

    if repaired > 0:
        print(f"Repaired {repaired} record(s).", file=sys.stderr)
    return repaired


try:
    from fastapi import FastAPI, HTTPException, Request
    from fastapi.responses import JSONResponse
    from pydantic import BaseModel

    class BufferRequest(BaseModel):
        content: str
        agent_name: Optional[str] = None
        local_id: Optional[str] = None
        session_id: Optional[str] = None
        turn_id: Optional[str] = None

    class SearchRequest(BaseModel):
        query: str
        session_id: Optional[str] = None
        since: Optional[str] = None
        until: Optional[str] = None

    class RepairRequest(BaseModel):
        max_records: Optional[int] = None

    class ShutdownRequest(BaseModel):
        root: str

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        global _srv_cfg, _srv_session, _srv_code_version
        _srv_cfg = _load_config()
        _srv_code_version = _code_version()  # after _load_config may rewrite it
        _srv_session = os.environ.get('N3MC_SESSION_ID') or str(uuid.uuid4())
        os.makedirs(MEMORY_DIR, exist_ok=True)

        from .core.database import get_connection, init_db, migrate_schema

        # spec §3.5: integrity_check on startup (once, not in fallback path)
        conn = _connect_checked('integrity_check')
        try:
            init_db(conn)
            migrate_schema(conn)
        finally:
            conn.close()

        # Preload embedding model (covers first-time download wait)
        try:
            from .core.processor import get_model
            get_model(_srv_cfg.get('embed_model'))
        except Exception as e:
            logger.warning(f"Model preload failed: {e}")

        yield

    app = FastAPI(lifespan=lifespan)

    @app.middleware('http')
    async def _host_guard(request: Request, call_next):
        # spec §3 (v1.5.0): DNS-rebinding guard on every endpoint
        if not _host_ok(request.headers.get('host')):
            return JSONResponse({'detail': 'Host not allowed'}, status_code=403)
        if 'origin' in request.headers:
            return JSONResponse({'detail': 'Origin not allowed'}, status_code=403)
        return await call_next(request)

    @app.get('/health')
    async def ep_health():
        return {
            'status':       'ok',
            'root':         os.path.abspath(HOME_DIR),
            'code_version': _srv_code_version or _code_version(),
            'pid':          os.getpid(),
        }

    @app.post('/shutdown')
    async def ep_shutdown(req: ShutdownRequest):
        if _norm(req.root) != _norm(HOME_DIR):
            raise HTTPException(status_code=403, detail='root mismatch')
        threading.Timer(0.3, _exit_server_process).start()
        return {'status': 'ok'}

    # spec §3 (v1.5.0): endpoints that embed or touch the DB are plain `def`
    # (run in the thread pool, /health stays responsive); one SQLite
    # connection per request.
    @app.post('/buffer')
    def ep_buffer(req: BufferRequest):
        # Looked up at call time so tests can patch processor.embed_passage.
        from .core.database import (
            get_connection, check_exact_duplicate, insert_memory, insert_memory_once, count_memories,
        )
        from .core.processor import embed_passage, purify_text
        from uuid_extensions import uuid7

        content = purify_text(req.content) if req.content else ''
        if not content.strip():
            return {'status': 'skipped', 'count': 0, 'reason': 'empty'}

        local = req.local_id   or _srv_cfg.get('local_id')
        sess  = req.session_id or _srv_session
        tid   = req.turn_id
        agent = req.agent_name

        conn = get_connection(DB_PATH)
        try:
            # spec §5.4 (v1.4.0): exact text only (same turn when turn_id is
            # given); checked before computing the embedding. No similarity dedup.
            if check_exact_duplicate(conn, content, turn_id=tid):
                return {'status': 'skipped', 'count': 0, 'reason': 'exact_duplicate'}

            vec = None
            try:
                if not embedding_index_compatible(conn, _srv_cfg.get('embed_model') or _DEFAULT_CONFIG['embed_model']):
                    raise RuntimeError('index model differs or reembedding is incomplete; run --reembed')
                vec = embed_passage(content)
            except Exception as e:
                logger.warning(f"Embed error: {e}")

            before = count_memories(conn)
            ts = datetime.now(timezone.utc).isoformat()
            rowid = insert_memory_once(
                conn, str(uuid7()), content, ts,
                owner_id=_srv_cfg['owner_id'],
                embedding=vec,
                expected_embed_model=_srv_cfg.get('embed_model') or _DEFAULT_CONFIG['embed_model'],
                local_id=local,
                agent_name=agent,
                session_id=sess,
                turn_id=tid,
            )
            if rowid is None:               # spec §5.4 (R04): saved meanwhile
                return {'status': 'skipped', 'count': 0, 'reason': 'exact_duplicate'}
            if count_memories(conn) == before:
                # spec §5.4: record count unchanged after INSERT → fatal
                return {'status': 'error',
                        'message': 'record count did not change after INSERT'}
            return {'status': 'ok', 'count': 1}
        finally:
            conn.close()

    @app.post('/search')
    def ep_search(req: SearchRequest):
        from .core.processor import hybrid_search
        try:
            since, until = _parse_time_range(req.since, req.until)
        except TimeBoundError as e:
            raise HTTPException(status_code=400, detail=str(e))
        sess = req.session_id or _srv_session
        return hybrid_search(
            DB_PATH, req.query or '', _srv_cfg, sess,
            since=since, until=until,
        )

    @app.post('/repair')
    def ep_repair(req: Optional[RepairRequest] = None):
        max_records = req.max_records if req is not None else None
        return {'status': 'ok', 'count': _repair_db(max_records)}

    @app.get('/list')
    def ep_list():
        from .core.database import get_connection, get_all_memories
        conn = get_connection(DB_PATH)
        try:
            rows = get_all_memories(conn)
            records = [
                {
                    'id':         r['id'],
                    'content':    r['content'],
                    'timestamp':  r['timestamp'],
                    'agent_name': r['agent_name'],
                }
                for r in rows
            ]
            return {'records': records, 'total': len(records)}
        finally:
            conn.close()

    # spec §3: Pro-only endpoints — stub returns 403 in Free edition
    @app.delete('/delete/{memory_id}')
    async def ep_delete(memory_id: str):
        raise HTTPException(status_code=403, detail='Pro feature')

    @app.post('/gc')
    async def ep_gc():
        raise HTTPException(status_code=403, detail='Pro feature')

    @app.post('/import')
    async def ep_import():
        raise HTTPException(status_code=403, detail='Pro feature')

except ImportError:
    app = None  # type: ignore


# ---------------------------------------------------------------------------
# CLI helpers
# ---------------------------------------------------------------------------


def _do_buffer(
    text: str, cfg: dict,
    agent_name: Optional[str] = None,
    session_id: Optional[str] = None,
    turn_id: Optional[str] = None,
    *,
    timeout: Optional[int] = None,
) -> None:
    global _NO_SERVER_REASON
    def _direct():
        try:
            _buffer_direct(text, cfg, agent_name=agent_name,
                           session_id=session_id, turn_id=turn_id)
        except Exception as e2:
            # spec §5.4: fatal failure warning (DB write failed)
            print(f"{_FATAL_SAVE_MSG} ({e2})", file=sys.stderr)
            # F11: the hook's stderr is read by nobody; the notice reaches the
            # next search output
            _notify('save_failed', _SAVE_FAILED_MSG.format(error=f"{type(e2).__name__}: {e2}"))
            # Let the hook entry point return a failure status to the host.
            raise RuntimeError('N3MC physical save failed') from e2

    # spec §3: another folder's server owns the port → never write to its DB.
    # No server for this command (still starting / failed to start): save
    # directly (spec §3 "PID file handling", "Starting the server").
    if _FOREIGN_SERVER_ROOT is not None or _NO_SERVER_REASON is not None:
        _direct()
        return

    payload = {
        'content':    text,
        'agent_name': agent_name,
        'session_id': session_id,
        'turn_id':    turn_id,
    }
    try:
        options = {} if timeout is None else {'timeout': timeout}
        result = _post(cfg, '/buffer', payload, **options)
    except Exception as e:
        print(f"Warning: HTTP buffer failed ({e}), using direct write.", file=sys.stderr)
    else:
        if isinstance(result, dict) and result.get('status') in ('ok', 'skipped'):
            return
        reason = result.get('message') if isinstance(result, dict) else 'invalid response'
        print(f"Warning: /buffer failed ({reason}), using direct write.",
              file=sys.stderr)
    if timeout is not None:
        # This hook may contain many chunks. After the first failed request,
        # avoid timing out again on every chunk.
        _NO_SERVER_REASON = 'the memory server could not save a chunk'
    _direct()


def _do_search(
    query: str, cfg: dict,
    since: Optional[str] = None,
    until: Optional[str] = None,
    current_session: Optional[str] = None,
    *,
    local_fallback: bool = False,
) -> None:
    """spec §5.4 (v1.4.0): print the result to stdout only (no file), on
    every invocation, including degraded states."""
    if not query or not query.strip():
        _emit(_status_md("_No relevant memories found._"))
        return

    payload: dict = {'query': query}
    if since:
        payload['since'] = since
    if until:
        payload['until'] = until
    if current_session:
        payload['session_id'] = current_session

    try:
        if _FOREIGN_SERVER_ROOT is not None:
            raise RuntimeError(f"another N3MC folder's server is using port {cfg.get('server_port')}")
        if _NO_SERVER_REASON is not None:
            raise RuntimeError(_NO_SERVER_REASON)
        options = {'timeout': 8} if local_fallback else {}
        result = _post(cfg, '/search', payload, **options)
        if not isinstance(result, dict):
            raise RuntimeError('invalid /search response')
        if result.get('status') == 'error':
            raise RuntimeError(result.get('message') or '/search error')
    except Exception as e:
        if not local_fallback or not os.path.isfile(DB_PATH):
            _emit(_status_md(f"_(memory search unavailable: {e})_"))
            return
        from .core.processor import hybrid_search
        try:
            result = hybrid_search(DB_PATH, query, cfg, current_session, since, until,
                                   keyword_only=True)
        except Exception as local_error:
            _emit(_status_md(f"_(memory search unavailable: {e}; local keyword search failed: {local_error})_"))
            return
        notices = ['The memory server is unavailable. Results use the local keyword index only.']
    else:
        notices = []

    try:
        md = render_memory_context(result, query, notices=notices + _take_notices())
    except Exception as e:
        md = _status_md(f"_(memory search unavailable: rendering failed: {e})_")
    _emit(md)


# ---------------------------------------------------------------------------
# CLI commands
# ---------------------------------------------------------------------------

def cmd_buffer(text: str, cfg: dict, agent_name: Optional[str] = None) -> None:
    ensure_server(cfg)
    _do_buffer(text, cfg, agent_name=agent_name, session_id=os.environ.get('N3MC_SESSION_ID'))


def cmd_search(
    query: str, cfg: dict,
    since: Optional[str] = None,
    until: Optional[str] = None,
) -> None:
    # A failed start falls through: _do_search then prints
    # "_(memory search unavailable: <reason>)_" (spec §5.4).
    ensure_server(cfg)
    _do_search(query, cfg, since=since, until=until,
               current_session=os.environ.get('N3MC_SESSION_ID'))


def cmd_repair(cfg: dict) -> int:
    if not ensure_server(cfg) and _FOREIGN_SERVER_ROOT is not None:
        print(
            f"N3MC: --repair skipped: port {cfg.get('server_port')} is used by "
            "another N3MC folder's server.",
            file=sys.stderr,
        )
        return 1
    if _NO_SERVER_REASON is not None:
        print(f"N3MC: --repair skipped: {_NO_SERVER_REASON}.", file=sys.stderr)
        return 1
    try:
        result = _post(cfg, '/repair', {})   # no limit: process everything
        if not isinstance(result, dict) or result.get('status') != 'ok':
            reason = result.get('message') if isinstance(result, dict) else 'invalid response'
            raise RuntimeError(reason or '/repair error')
        count = result.get('count', 0)
        if count > 0:
            print(f"Repaired {count} record(s).", file=sys.stderr)
    except Exception as e:
        print(f"Repair failed: {e}", file=sys.stderr)
        return 1
    return 0


def _open_db_readonly_ready():
    from .core.database import get_connection, init_db, migrate_schema
    conn = get_connection(DB_PATH)
    try:
        init_db(conn)
        migrate_schema(conn)
        return conn
    except BaseException:
        conn.close()
        raise


def _print_tsv_record(record: sqlite3.Row) -> None:
    fields = (record['id'], record['timestamp'], record['agent_name'] or '-', record['content'][:80])
    print('\t'.join(re.sub(r'[\t\r\n]', ' ', field) for field in fields))


def cmd_list(
    cfg: dict,
    since: Optional[str] = None,
    until: Optional[str] = None,
    fmt: str = 'tsv',
) -> None:
    from .core.database import get_all_memories
    os.makedirs(MEMORY_DIR, exist_ok=True)
    if not os.path.exists(DB_PATH):
        if fmt != 'jsonl':
            print("Total: 0 records")
        return

    conn = _open_db_readonly_ready()
    try:
        rows = get_all_memories(conn, since=since, until=until)
        if fmt == 'jsonl':
            for r in rows:
                record = {key: r[key] for key in r.keys() if key != 'rowid'}
                state = conn.execute('SELECT state, replacement_turn_id FROM turn_lifecycle WHERE turn_id = ?',
                                     (r['turn_id'],)).fetchone()
                record['state'] = state['state'] if state else 'active'
                record['replacement_turn_id'] = state['replacement_turn_id'] if state else None
                print(json.dumps(record, ensure_ascii=False))
        else:
            for r in rows:
                # spec §6 test 2: [UUIDv7]\t[timestamp]\t[agent_name]\t[content[:80]]
                _print_tsv_record(r)
        if fmt != 'jsonl':
            print(f"Total: {len(rows)} records")
    finally:
        conn.close()


def cmd_recall_thread(
    turn_id: str,
    cfg: dict,
    before: int = 2,
    after: int = 2,
    fmt: str = 'tsv',
) -> None:
    """spec §3.6: return turn_id's records plus N surrounding turns."""
    from .core.database import get_thread_context
    os.makedirs(MEMORY_DIR, exist_ok=True)
    if not os.path.exists(DB_PATH):
        print(f"No DB found at {DB_PATH}", file=sys.stderr)
        return

    conn = _open_db_readonly_ready()
    try:
        rows = get_thread_context(conn, turn_id, before=before, after=after)
        if fmt == 'jsonl':
            for r in rows:
                print(json.dumps({
                    'id':         r['id'],
                    'timestamp':  r['timestamp'],
                    'agent_name': r['agent_name'],
                    'turn_id':    r['turn_id'],
                    'content':    r['content'],
                }, ensure_ascii=False))
        else:
            for r in rows:
                _print_tsv_record(r)
        if fmt != 'jsonl':
            print(f"Total: {len(rows)} records")
    finally:
        conn.close()


def cmd_show_turn(turn_id: str, cfg: dict) -> None:
    """spec §4.5: full text of one exchange (no truncation)."""
    from .core.database import get_memories_by_turn_id
    from .core.processor import _fmt_saved
    if not os.path.exists(DB_PATH):
        print("Total: 0 records")
        return
    conn = _open_db_readonly_ready()
    try:
        rows = get_memories_by_turn_id(conn, turn_id)
        for r in rows:
            print(f"--- {r['id']} saved={_fmt_saved(r['timestamp'])} ---")
            print(r['content'])
        print(f"Total: {len(rows)} records")
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# --stop: housekeeping (spec §4)
# ---------------------------------------------------------------------------

# spec §4 --stop housekeeping (v1.5.0)
_TURN_ID_MAX_AGE_SECONDS = 30 * 86400
_AUDIT_LOG_MAX_BYTES = 50 * 1024 * 1024


def _housekeeping() -> None:
    """Delete stale hook state and rotate audit.log above 50 MB."""
    import glob
    now = time.time()
    paths = (glob.glob(os.path.join(MEMORY_DIR, 'turn_id_*.txt')) +
             glob.glob(os.path.join(MEMORY_DIR, 'skip_*')))
    for path in paths:
        try:
            if now - os.path.getmtime(path) > _TURN_ID_MAX_AGE_SECONDS:
                os.remove(path)
        except OSError as e:
            print(f"Warning: could not remove {path}: {e}", file=sys.stderr)
    try:
        if os.path.getsize(AUDIT_LOG) > _AUDIT_LOG_MAX_BYTES:
            os.replace(AUDIT_LOG, AUDIT_LOG + '.1')
    except FileNotFoundError:
        pass
    except OSError as e:
        print(f"Warning: could not rotate {AUDIT_LOG}: {e}", file=sys.stderr)


def cmd_stop(cfg: dict) -> None:
    """Run Codex hook housekeeping without modifying project instructions."""
    try:
        _housekeeping()
    except Exception as e:
        print(f"Warning: --stop housekeeping failed: {e}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Server runner
# ---------------------------------------------------------------------------

def run_server(cfg: dict) -> None:
    import uvicorn
    host = cfg.get('bind_host') or '127.0.0.1'
    if host != '127.0.0.1':
        print(
            f"WARNING: bind_host is {host}. The N3MC API (search, list, "
            "/shutdown, ...) has no authentication and becomes reachable from "
            "the network. Keep the default 127.0.0.1 unless you know what you "
            "are doing.",
            file=sys.stderr,
        )
    uvicorn.run(
        app, host=host, port=cfg.get('server_port', 18520),
        log_level='error',
    )


# ---------------------------------------------------------------------------
# n3mc --init  —  register the Codex hooks
# ---------------------------------------------------------------------------

def cmd_init() -> int:
    """Set up the data directory and register global Codex hooks."""
    from .codex_install import install
    os.makedirs(MEMORY_DIR, exist_ok=True)
    print(f"Data directory: {HOME_DIR}")

    cfg = _load_config()
    print(f"Config: {CONFIG_FILE}")
    print(f"  owner_id = {cfg['owner_id']}")
    print(f"  port     = {cfg['server_port']}")

    return install()


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description='N3MemoryCore CLI')
    grp = parser.add_mutually_exclusive_group()
    grp.add_argument('--init',   action='store_true',
                     help='Set up ~/.n3mc/ and register Codex hooks')
    grp.add_argument('--buffer', metavar='TEXT', nargs='?', const='-')
    grp.add_argument('--search', metavar='QUERY')
    grp.add_argument('--repair', action='store_true')
    grp.add_argument('--reembed', action='store_true',
                     help='Re-embed every record with the configured embed_model')
    grp.add_argument('--list',   action='store_true')
    grp.add_argument('--recall-thread', metavar='TURN_ID', dest='recall_thread')
    grp.add_argument('--show-turn', metavar='TURN_ID', dest='show_turn',
                     help='Print the full text of one exchange')
    grp.add_argument('--stop',   action='store_true')
    grp.add_argument('--run-server',       action='store_true', dest='run_server')
    grp.add_argument('--backup', metavar='NEW_DIRECTORY', help='Create a verified SQLite snapshot')
    grp.add_argument('--restore-backup', metavar='DIRECTORY', help='Restore a snapshot to a new home')
    grp.add_argument('--export-records', metavar='NEW_FILE', help='Export text and all provenance as JSONL')
    grp.add_argument('--forget-turn', metavar='TURN_ID', help='Preview deletion of a complete turn')
    grp.add_argument('--supersede-turn', metavar='TURN_ID', help='Mark an old turn as replaced')
    parser.add_argument('--replacement-turn', metavar='TURN_ID')
    parser.add_argument('--to-home', metavar='NEW_DIRECTORY')
    parser.add_argument('--yes', action='store_true', help='Apply a previewed lifecycle change')

    parser.add_argument('--agent-id', dest='agent_id', default=None)
    parser.add_argument('--since', default=None,
                        help='Filter from (2026-11-13 or 2026-11-13T09:00; local time unless an offset is given)')
    parser.add_argument('--until', default=None,
                        help='Filter until (a date means the end of that day)')
    parser.add_argument('--before', type=int, default=2, help='Turns before target (default 2)')
    parser.add_argument('--after',  type=int, default=2, help='Turns after target (default 2)')
    parser.add_argument('--format', dest='fmt', default='tsv',
                        choices=['tsv', 'jsonl'], help='Output format for --list/--recall-thread')

    args = parser.parse_args()

    if args.replacement_turn and not args.supersede_turn:
        parser.error('--replacement-turn requires --supersede-turn')
    if args.supersede_turn and not args.replacement_turn:
        parser.error('--supersede-turn requires --replacement-turn')
    if bool(args.restore_backup) != bool(args.to_home):
        parser.error('--restore-backup and --to-home must be used together')
    if args.yes and not (args.forget_turn or args.supersede_turn):
        parser.error('--yes requires --forget-turn or --supersede-turn')

    if any((args.backup, args.restore_backup, args.export_records, args.forget_turn, args.supersede_turn)):
        from .maintenance import backup_database, restore_database, export_records, change_turn
        try:
            if args.backup:
                result = backup_database(DB_PATH, CONFIG_FILE, args.backup)
            elif args.restore_backup:
                result = restore_database(args.restore_backup, args.to_home)
            elif args.export_records:
                result = export_records(DB_PATH, args.export_records)
            else:
                result = change_turn(DB_PATH, args.forget_turn or args.supersede_turn,
                                     replacement=args.replacement_turn, apply=args.yes)
            print(json.dumps(result, ensure_ascii=False))
        except (OSError, ValueError, RuntimeError, sqlite3.Error) as exc:
            print(f'N3MC: {exc}', file=sys.stderr)
            raise SystemExit(1)
        return

    if args.init:
        sys.exit(cmd_init())

    # spec §3.6 (v1.5.0): unreadable bounds → one stderr line, exit status 2
    try:
        since, until = _parse_time_range(args.since, args.until)
    except TimeBoundError as e:
        print(str(e), file=sys.stderr)
        sys.exit(2)

    cfg = _load_config()

    if args.run_server:
        run_server(cfg)
    elif args.buffer is not None:
        text = sys.stdin.read() if args.buffer == '-' else args.buffer
        if text.strip():
            cmd_buffer(text, cfg, agent_name=args.agent_id)
    elif args.search is not None:
        from .core.processor import sanitize_surrogates
        cmd_search(sanitize_surrogates(args.search), cfg, since=since, until=until)
    elif args.repair:
        sys.exit(cmd_repair(cfg))
    elif args.reembed:
        sys.exit(cmd_reembed(cfg))
    elif args.list:
        cmd_list(cfg, since=since, until=until, fmt=args.fmt)
    elif args.recall_thread:
        cmd_recall_thread(
            args.recall_thread, cfg,
            before=args.before, after=args.after, fmt=args.fmt,
        )
    elif args.show_turn:
        cmd_show_turn(args.show_turn, cfg)
    elif args.stop:
        cmd_stop(cfg)
    else:
        parser.print_help()


if __name__ == '__main__':
    main()
