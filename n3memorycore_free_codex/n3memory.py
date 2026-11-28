"""N3MemoryCore (Free): CLI + resident FastAPI memory server.

Everything is saved by hooks (UserPromptSubmit + Stop). Saving is immediate and physical
(INSERT + COMMIT per record, PRAGMA synchronous=FULL): the "Immutable Memory" invariant.
"""
import os as _os
import sys as _sys

if __name__ == "__main__":
    # Safe import path. Started as `python -m <package>.<module>`, Python has put the current folder
    # first on sys.path, so a file there named like a module imported below would run inside this
    # program. Drop that entry, unless this package itself lives in the current folder (a source
    # checkout run in place). Nothing else may be imported before this block.
    try:
        _cwd = _os.path.normcase(_os.path.abspath(_os.getcwd()))
        _pkg_parent = _os.path.normcase(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
        if _sys.path and _os.path.normcase(_os.path.abspath(_sys.path[0])) == _cwd and _pkg_parent != _cwd:
            del _sys.path[0]
    except Exception:  # noqa: BLE001
        pass

import argparse
import hashlib
import json
import math
import re
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .paths import (
    HOME_DIR, MEMORY_DIR, DB_PATH, PID_FILE, AUDIT_LOG, CONFIG_FILE, NOTICES_FILE,
    SERVER_LOG, SERVER_START_FAILED_FILE, python_cmd,
)
from .core.database import (
    get_connection, init_db, migrate_schema, insert_memory, insert_memory_once,
    check_exact_duplicate, search_vector, find_unindexed_memories,
    strip_fts_punctuation, fts_index_text, FTS_TEXT_RULES,
    serialize_vector, bigram_text, get_meta, set_meta, delete_meta,
    count_memories, get_memories_by_turn_id, vec_dim,
)
from .core.processor import (
    embed_passage, embed_query, cosine_sim_from_l2, hybrid_search,
    chunk_text, add_chunk_prefixes, purify_text, render_memory_context, sanitize_surrogates,
)
from .core import processor as _processor
from .core import database as _database

from uuid_extensions import uuid7


def _new_id():
    return str(uuid7())


# ============================================================ constants

DEFAULT_CONFIG = {
    "owner_id": None,
    "local_id": None,
    "bind_host": "127.0.0.1",
    "server_port": 18526,
    "connect_server_port": None,
    "connect_server_root": None,
    "embed_model": "intfloat/multilingual-e5-base",
    "half_life_days": 90,
    "bm25_min_threshold": 0.1,
    "search_result_limit": 20,
    "min_score": 0.2,
    "search_query_max_chars": 2000,
    "vector_min_cos": 0.85,
    "relative_min_score_ratio": 0.6,
    "min_results": 3,
    "pair_top_n": 3,
    "pair_max_chars": 3000,
    "version_order_enabled": True,
    "version_sim_threshold": 0.98,
    "version_min_chars": 100,
    "reply_sim_rerank_enabled": False,
    "reply_sim_alpha": 0.3,
    "reply_sim_floor": 0.80,
    "reply_sim_span": 0.15,
}

_INT_RANGES = {
    "server_port": (1, 65535), "search_result_limit": (1, 1365),
    "pair_top_n": (1, None), "pair_max_chars": (1, None), "search_query_max_chars": (1, None),
    "version_min_chars": (1, None), "min_results": (0, None),
}
_UNIT_KEYS = {"min_score", "vector_min_cos", "relative_min_score_ratio", "version_sim_threshold",
              "reply_sim_alpha", "reply_sim_floor"}

AGENT_NAME = "codex"
NOTICE_INTERVAL_SECONDS = 86400
AUDIT_ROTATE_BYTES = 50 * 1024 * 1024
HTTP_TIMEOUT = 30
SERVER_WAIT_SECONDS = 60

_FOREIGN_SERVER_ROOT = None
_QUICK_CHECKED = False
_SERVER_PORT = None          # the port this server process listens on (Host check)
_SERVER_STATE = {}
_CFG_CACHE = None
_CFG_SOURCE = None         # config.json content _CFG_CACHE comes from (bytes; None: no readable file)


def _norm(p):
    return _os.path.normcase(_os.path.abspath(p))


def _reconfigure_streams():
    for name in ("stdin", "stdout", "stderr"):
        s = getattr(sys, name, None)
        if s is not None and hasattr(s, "reconfigure"):
            try:
                s.reconfigure(encoding="utf-8", newline="\n")
            except Exception:  # noqa: BLE001
                pass


def _ensure_dirs():
    _os.makedirs(MEMORY_DIR, exist_ok=True)


def _atomic_write_json(path, obj):
    d = _os.path.dirname(path)
    _os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, prefix="." + _os.path.basename(path) + ".")
    try:
        text = json.dumps(obj, indent=2, ensure_ascii=False) + "\n"
        with _os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        _os.replace(tmp, path)
        return text
    except BaseException:
        try:
            _os.unlink(tmp)
        except OSError:
            pass
        raise


# ============================================================ audit + notices

def _audit_append(rec):
    try:
        _ensure_dirs()
        with open(AUDIT_LOG, "a", encoding="utf-8", errors="replace") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        return True
    except Exception as e:  # noqa: BLE001
        print(f"N3MC: could not write audit.log ({type(e).__name__}: {e})", file=sys.stderr)
        return False



def _notices_read():
    try:
        with open(NOTICES_FILE, "r", encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def _notices_write(d):
    try:
        _atomic_write_json(NOTICES_FILE, d)
    except Exception as e:  # noqa: BLE001
        print(f"N3MC: could not write notices.json ({e})", file=sys.stderr)


def _notify(key, message):
    print(f"N3MC: {message}", file=sys.stderr)
    d = _notices_read()
    ent = d.get(key)
    if isinstance(ent, dict) and ent.get("message") == message:
        return
    d[key] = {"message": message, "last_shown": None}
    _notices_write(d)
    _audit_append({"ts": datetime.now(timezone.utc).isoformat(), "hook": "notice", "key": key, "message": message})


def _clear_notice(key):
    d = _notices_read()
    if key in d:
        del d[key]
        _notices_write(d)


def _take_notices():
    d = _notices_read()
    now, out, changed = time.time(), [], False
    for key, ent in d.items():
        if not isinstance(ent, dict):
            continue
        last = ent.get("last_shown")
        if type(last) not in (int, float) or not now - NOTICE_INTERVAL_SECONDS < last <= now:
            out.append(ent.get("message", ""))
            ent["last_shown"] = now
            changed = True
    if changed:
        _notices_write(d)
    return [m for m in out if m]


# ============================================================ config

def _config_value_ok(key, value):
    if key == "connect_server_port":
        return value is None or (type(value) is int and 1 <= value <= 65535)
    if key == "connect_server_root":
        return value is None or (isinstance(value, str) and _os.path.isabs(value) and "\0" not in value)
    if key not in DEFAULT_CONFIG or DEFAULT_CONFIG[key] is None:
        return True
    default = DEFAULT_CONFIG[key]
    if isinstance(default, bool):
        return isinstance(value, bool)
    if isinstance(default, str):
        return isinstance(value, str)
    if isinstance(value, bool):
        return False
    if key in _INT_RANGES:
        lo, hi = _INT_RANGES[key]
        return isinstance(value, int) and value >= lo and (hi is None or value <= hi)
    if not isinstance(value, (int, float)):
        return False
    if key in _UNIT_KEYS:
        return 0 <= value <= 1
    if key in ("half_life_days", "reply_sim_span"):
        return value > 0
    if key == "bm25_min_threshold":
        return value >= 0
    return True


class _ConfigReadError(Exception):
    """config.json could not be parsed; `raw` holds the bytes read (None when the file could not be read)."""

    def __init__(self, cause, raw):
        super().__init__(str(cause))
        self.raw = raw


def _read_config_file():
    """Read config.json -> (parsed JSON, bytes read). A file touched in the last 2 s is retried (it may
    still be being written). On failure raises _ConfigReadError carrying the bytes of the last read."""
    attempts = 1
    try:
        if time.time() - _os.path.getmtime(CONFIG_FILE) <= 2:
            attempts = 20
    except OSError:
        pass
    last, last_raw = None, None
    for i in range(attempts):
        raw = None
        try:
            with open(CONFIG_FILE, "rb") as f:
                raw = f.read()
            return json.loads(raw.decode("utf-8")), raw
        except Exception as e:  # noqa: BLE001
            last, last_raw = e, raw
            if i < attempts - 1:
                time.sleep(0.05)
    raise _ConfigReadError(last, last_raw)


CONFIG_LOCK_WAIT_SECONDS = 10
CONFIG_LOCK_STALE_SECONDS = 10


def _config_lock_path():
    return _os.path.join(MEMORY_DIR, "config.lock")


def _acquire_config_lock():
    """Take .memory/config.lock (exclusive create; retry every 0.05 s for up to 10 s; a lock older than
    10 s is stale and removed). Returns True when the lock is held."""
    path = _config_lock_path()
    end = time.time() + CONFIG_LOCK_WAIT_SECONDS
    while True:
        try:
            fd = _os.open(path, _os.O_CREAT | _os.O_EXCL | _os.O_WRONLY)
            try:
                _os.write(fd, str(_os.getpid()).encode("ascii"))
            finally:
                _os.close(fd)
            return True
        except FileExistsError:
            try:
                if time.time() - _os.path.getmtime(path) > CONFIG_LOCK_STALE_SECONDS:
                    _os.unlink(path)
                    continue
            except OSError:
                continue  # removed meanwhile: try again at once
        except OSError:
            return False
        if time.time() >= end:
            return False
        time.sleep(0.05)


def _release_config_lock():
    try:
        _os.unlink(_config_lock_path())
    except OSError:
        pass


def _merge_config(raw):
    """Validated settings of a parsed config.json (defaults for missing keys) and the bad keys."""
    bad, merged = [], {}
    for k, v in raw.items():
        if k in DEFAULT_CONFIG and not _config_value_ok(k, v):
            bad.append(k)
        else:
            merged[k] = v
    for k, v in DEFAULT_CONFIG.items():
        if k not in merged:
            merged[k] = v
    return merged, bad


def _id_ok(v):
    return isinstance(v, str) and bool(v)


def _needs_fill(raw):
    return any(k not in raw for k in DEFAULT_CONFIG) or not all(_id_ok(raw.get(k)) for k in ("owner_id", "local_id"))


def _recover_id(column):
    try:
        if not _os.path.exists(DB_PATH):
            return None
        conn = sqlite3.connect(DB_PATH, timeout=5)
        try:
            row = conn.execute(f"SELECT {column} FROM memories GROUP BY {column} "
                               "ORDER BY COUNT(*) DESC LIMIT 1").fetchone()
        finally:
            conn.close()
        return row[0] if row and row[0] else None
    except Exception:  # noqa: BLE001
        return None


def _fill_ids_in_memory(merged):
    for idk in ("owner_id", "local_id"):
        if not _id_ok(merged.get(idk)):
            merged[idk] = _recover_id(idk) or str(uuid.uuid4())


def _notify_bad(bad):
    _notify("config_type", "These config.json items have the wrong type or are out of range and were "
            f"ignored (defaults used): {', '.join(sorted(bad))}")


def _fill_config_locked(raw, src):
    """Add the missing keys / IDs of an existing, valid config.json under .memory/config.lock (review #2):
    read the file again inside the lock and add only what is still missing, so every process ends with
    the IDs on disk. Returns (settings, the config.json content they come from)."""
    locked = _acquire_config_lock()
    try:
        try:
            raw2, src2 = _read_config_file()
            if isinstance(raw2, dict):
                raw, src = raw2, src2
        except Exception:  # noqa: BLE001
            pass  # vanished or unreadable now: work from the first read, as before
        merged, bad = _merge_config(raw)
        if bad:  # edited meanwhile with a bad value: leave the file alone
            _fill_ids_in_memory(merged)
            _notify_bad(bad)
            return merged, src
        if not _needs_fill(raw):
            return merged, src
        _fill_ids_in_memory(merged)
        out = dict(raw)
        for k, v in merged.items():
            if k not in out or (k in ("owner_id", "local_id") and out.get(k) != v):
                out[k] = v
        try:
            src = _atomic_write_json(CONFIG_FILE, out).encode("utf-8")
        except Exception as e:  # noqa: BLE001
            print(f"N3MC: could not update config.json ({e})", file=sys.stderr)
        return merged, src
    finally:
        if locked:
            _release_config_lock()


def _load_config():
    """Load config.json. _CFG_SOURCE is set to the content the settings come from (the bytes read, or the
    content written), so the server's code_version is computed from it, not from a second read (#9)."""
    global _CFG_CACHE, _CFG_SOURCE
    _ensure_dirs()
    cfg = dict(DEFAULT_CONFIG)
    if not _os.path.exists(CONFIG_FILE):
        cfg["owner_id"] = _recover_id("owner_id") or str(uuid.uuid4())
        cfg["local_id"] = _recover_id("local_id") or str(uuid.uuid4())
        text = json.dumps(cfg, indent=2, ensure_ascii=False) + "\n"
        try:
            with open(CONFIG_FILE, "x", encoding="utf-8") as f:
                f.write(text)
        except FileExistsError:
            return _load_config()
        _clear_notice("config_unreadable")
        _clear_notice("config_type")
        _CFG_CACHE, _CFG_SOURCE = cfg, text.encode("utf-8")
        return cfg
    try:
        raw, src = _read_config_file()
        if not isinstance(raw, dict):
            raise _ConfigReadError(ValueError("config.json is not a JSON object"), src)
    except Exception as e:  # noqa: BLE001
        _notify("config_unreadable", f"{CONFIG_FILE} could not be read ({e}). It was left untouched; default "
                "settings are in use. Fix the file to apply your settings.")
        cfg["owner_id"] = _recover_id("owner_id") or str(uuid.uuid4())
        cfg["local_id"] = _recover_id("local_id") or str(uuid.uuid4())
        _CFG_CACHE, _CFG_SOURCE = cfg, getattr(e, "raw", None)
        return cfg
    _clear_notice("config_unreadable")
    merged, bad = _merge_config(raw)
    if bad:
        _fill_ids_in_memory(merged)
        _notify_bad(bad)
    else:
        _clear_notice("config_type")
        if _needs_fill(raw):  # fill in missing keys / ids and save (the file is valid)
            merged, src = _fill_config_locked(raw, src)
    _CFG_CACHE, _CFG_SOURCE = merged, src
    return merged


def get_config():
    return _CFG_CACHE if _CFG_CACHE is not None else _load_config()


# ============================================================ time bounds

_DATE_ONLY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _parse_time_bound(value, upper=False):
    """Parse --since/--until into a UTC ISO string comparable with stored timestamps."""
    v = (value or "").strip()
    try:
        if _DATE_ONLY_RE.match(v):
            d = datetime.fromisoformat(v)
            dt = d.replace(hour=23, minute=59, second=59, microsecond=999999) if upper else d
        else:
            if len(v) < 11 or v[10] not in ("T", "t", " "):
                raise ValueError("missing date/time separator")
            dt = datetime.fromisoformat(v[:-1] + "+00:00" if v.endswith(("Z", "z")) else v)
    except ValueError:
        raise ValueError(f"cannot read '{value}' (use 2026-11-13 or 2026-11-13T09:00)")
    if dt.tzinfo is None:
        try:
            dt = dt.astimezone()  # naive values are read as local time
        except (ValueError, OverflowError, OSError):
            dt = dt.replace(tzinfo=timezone.utc)
    try:
        return dt.astimezone(timezone.utc).isoformat()
    except OverflowError:
        boundary = datetime.min if dt.utcoffset() > timedelta(0) else datetime.max
        return boundary.replace(tzinfo=timezone.utc).isoformat()


def _time_bounds(since, until):
    bounds = []
    for flag, value, upper in (("--since", since, False), ("--until", until, True)):
        try:
            bounds.append(None if value is None else _parse_time_bound(value, upper))
        except ValueError as exc:
            raise ValueError(f"{flag}: {exc}") from None
    lower, upper = bounds
    if lower is not None and upper is not None and lower > upper:
        raise ValueError("--since is later than --until")
    return lower, upper


# ============================================================ DB open / corruption

class _DbCorrupt(Exception):
    pass


def _is_corruption_error(e):
    if not isinstance(e, sqlite3.DatabaseError) or isinstance(e, sqlite3.OperationalError):
        return False
    msg = str(e).lower()
    return "file is not a database" in msg or "malformed" in msg


def _connect_checked(pragma=None):
    conn = get_connection(DB_PATH)
    if pragma:
        try:
            rows = conn.execute(f"PRAGMA {pragma}").fetchall()
        except BaseException:
            conn.close()
            raise
        if not (len(rows) == 1 and str(rows[0][0]).lower() == "ok"):
            conn.close()
            raise _DbCorrupt(f"PRAGMA {pragma} returned {[tuple(r) for r in rows][:3]}")
    return conn


def _quarantine_db():
    stamp = datetime.now().strftime("%Y%m%d%H%M%S")
    n, suffix = 1, ""
    while _os.path.exists(f"{DB_PATH}.corrupt-{stamp}{suffix}.bak"):
        n += 1
        suffix = f"-{n}"
    bak = f"{DB_PATH}.corrupt-{stamp}{suffix}.bak"
    _os.replace(DB_PATH, bak)
    for ext in ("-wal", "-shm"):
        if _os.path.exists(DB_PATH + ext):
            _os.replace(DB_PATH + ext, bak + ext)
    msg = (f"The memory DB failed its integrity check and was set aside as {bak}. A new empty DB is in use. "
           f"To recover records: sqlite3 {bak} .recover | sqlite3 recovered.db")
    print("N3MC WARNING: " + msg, file=sys.stderr)
    _notify("db_corrupt", msg)
    return bak


def _open_db(pragma=None):
    """Open the DB (optionally integrity-checked), quarantining a corrupt file. Schema is initialised."""
    _ensure_dirs()
    try:
        conn = _connect_checked(pragma)
    except Exception as e:  # noqa: BLE001
        if isinstance(e, _DbCorrupt) or _is_corruption_error(e):
            _quarantine_db()
            conn = _connect_checked(None)
        else:
            raise
    try:
        init_db(conn)
    except Exception as e:  # noqa: BLE001
        conn.close()
        if _is_corruption_error(e):
            _quarantine_db()
            conn = _connect_checked(None)
            init_db(conn)
        else:
            raise
    return conn


def _open_db_direct():
    """DB for the direct (no server) paths: quick_check at most once per process."""
    global _QUICK_CHECKED
    pragma = None
    if not _QUICK_CHECKED:
        _QUICK_CHECKED = True
        pragma = "quick_check"
    return _open_db(pragma)


def _read_db_if_exists():
    if not _os.path.exists(DB_PATH):
        return None
    conn = sqlite3.connect(Path(DB_PATH).resolve().as_uri() + "?mode=ro", uri=True,
                           timeout=_database.BUSY_TIMEOUT_SECONDS)
    conn.row_factory = sqlite3.Row
    return conn


# ============================================================ code version

_FROM_DISK = object()


def compute_code_version(config_source=_FROM_DISK):
    """config_source: the config.json content to hash (bytes, or None for no readable file). By default
    the file is read (the client). The server passes the content _load_config used (review #9)."""
    h = hashlib.sha256()
    base = _os.path.dirname(_os.path.abspath(__file__))
    package = Path(base)
    sources = sorted((p for p in package.rglob("*.py") if "__pycache__" not in p.parts),
                     key=lambda p: p.relative_to(package).as_posix())
    for source in sources:
        h.update(source.relative_to(package).as_posix().encode("utf-8"))
        try:
            h.update(source.read_bytes())
        except OSError:
            h.update(b"?")
    raw = config_source
    if raw is _FROM_DISK:
        try:
            with open(CONFIG_FILE, "rb") as f:
                raw = f.read()
        except OSError:
            raw = None
    if raw is not None:
        try:
            h.update(json.dumps(json.loads(raw.decode("utf-8")), sort_keys=True).encode("utf-8"))
        except Exception:  # noqa: BLE001
            h.update(raw)
    return h.hexdigest()[:16]


def _server_code_version():
    """code_version of this server: from the config.json content its settings were loaded from (#9)."""
    get_config()
    return compute_code_version(_CFG_SOURCE)


# ============================================================ storing

def _store_record(conn, cfg, content, agent_name=None, local_id=None, session_id=None, turn_id=None,
                  embed=True):
    """Save one record. Returns the response dict used by /buffer."""
    content = purify_text(content or "")
    if not content.strip():
        return {"status": "skipped", "count": 0, "reason": "empty"}
    if check_exact_duplicate(conn, content, turn_id=turn_id):
        return {"status": "skipped", "count": 0, "reason": "exact_duplicate"}
    vec = None
    if embed:
        try:
            vec = embed_passage(content, cfg.get("embed_model"))
        except Exception as e:  # noqa: BLE001
            print(f"N3MC: embedding unavailable ({type(e).__name__}); saved without a vector", file=sys.stderr)
    before = count_memories(conn)
    rid = insert_memory_once(conn, _new_id(), content, datetime.now(timezone.utc).isoformat(),
                             cfg["owner_id"], local_id or cfg["local_id"], agent_name, session_id,
                             turn_id=turn_id, embedding=vec)
    if rid is None:
        return {"status": "skipped", "count": 0, "reason": "exact_duplicate"}
    if count_memories(conn) <= before:
        return {"status": "error", "message": "record count did not change after INSERT"}
    return {"status": "ok", "count": 1}


# ============================================================ repair

def _repair(conn, cfg, max_records=None):
    """Repair un-indexed records and run one-time migrations. Returns the number of records changed."""
    changed = 0
    budget = max_records
    if budget is not None and budget <= 0:
        return 0
    # --- meta: model of the stored vectors
    if get_meta(conn, "embed_model") is None:
        model = cfg["embed_model"]
        has_vec = conn.execute("SELECT 1 FROM memories_vec LIMIT 1").fetchone() is not None
        if has_vec:
            try:
                with open(_os.path.join(MEMORY_DIR, "vec_model.txt"), "r", encoding="utf-8") as f:
                    model = f.read().strip() or model
            except OSError:
                pass
        set_meta(conn, "embed_model", model)
        dim = vec_dim(conn)  # from the table itself, never EMBED_DIM (review #3)
        if dim is not None:
            set_meta(conn, "embed_dim", dim)
        set_meta(conn, "embed_model_at", datetime.now(timezone.utc).isoformat())
        conn.commit()
    recorded = get_meta(conn, "embed_model")
    if recorded != cfg["embed_model"]:
        n = count_memories(conn)
        _notify("embed_model_mismatch",
                f"The stored vectors were made with {recorded}, but config.json sets embed_model to "
                f"{cfg['embed_model']}. Search quality is degraded until they are re-made: run n3mc-free-codex --reembed "
                f"(it re-embeds all {n} records with {cfg['embed_model']}), or set embed_model back to {recorded}.")
    else:
        _clear_notice("embed_model_mismatch")
    processed = 0
    # --- one-time FTS punctuation clean-up (keyset batches, resumable through meta.fts_punct_cursor)
    if get_meta(conn, "fts_punct_cleaned") is None:
        last = int(get_meta(conn, "fts_punct_cursor", 0))
        finished = True
        while True:
            page_size = 200 if budget is None else min(200, budget - processed)
            rows = conn.execute(
                "SELECT m.rowid AS rid, m.content AS c, f.content AS fc FROM memories m "
                "JOIN memories_fts f ON f.rowid = m.rowid WHERE m.rowid > ? ORDER BY m.rowid LIMIT ?",
                (last, page_size)).fetchall()
            if not rows:
                break
            for r in rows:
                want = strip_fts_punctuation(fts_index_text(r["c"]))
                if r["fc"] != want:
                    conn.execute("UPDATE memories_fts SET content=? WHERE rowid=?", (want, r["rid"]))
                    changed += 1
                last = r["rid"]
                processed += 1
            set_meta(conn, "fts_punct_cursor", last)  # same transaction as the rewrites of this batch
            conn.commit()
            if budget is not None and processed >= budget:
                finished = False
                break
        if finished:
            set_meta(conn, "fts_punct_cleaned", "1")
            delete_meta(conn, "fts_punct_cursor")
            conn.commit()
    if budget is not None:
        budget -= processed
    # --- one-time bigram index fill
    if get_meta(conn, "fts_bigram") is None:
        while budget is None or budget > 0:
            limit = 200 if budget is None else min(200, budget)
            rows = conn.execute(
                "SELECT m.rowid AS rid, m.content AS c FROM memories m LEFT JOIN memories_fts_bi b "
                "ON b.rowid = m.rowid WHERE b.rowid IS NULL ORDER BY m.rowid LIMIT ?", (limit,)).fetchall()
            if not rows:
                set_meta(conn, "fts_bigram", "1")
                conn.commit()
                break
            for r in rows:
                conn.execute("INSERT OR REPLACE INTO memories_fts_bi(rowid, content) VALUES (?, ?)",
                             (r["rid"], bigram_text(fts_index_text(r["c"]))))
            conn.commit()
            if budget is not None:
                budget -= len(rows)
    # Rebuild indexes produced with older text rules. Each bounded transaction
    # advances its cursor atomically with the two aligned FTS rows.
    while budget is None or budget > 0:
        conn.execute("BEGIN IMMEDIATE")
        try:
            if get_meta(conn, "fts_text_rules") == FTS_TEXT_RULES:
                conn.commit()
                break
            cursor = int(get_meta(conn, "fts_text_cursor", 0))
            limit = 200 if budget is None else min(200, budget)
            rows = conn.execute("SELECT rowid, content FROM memories WHERE rowid > ? ORDER BY rowid LIMIT ?",
                                (cursor, limit)).fetchall()
            for row in rows:
                rid = row["rowid"]
                content = fts_index_text(row["content"])
                conn.execute("DELETE FROM memories_fts WHERE rowid=?", (rid,))
                conn.execute("DELETE FROM memories_fts_bi WHERE rowid=?", (rid,))
                conn.execute("INSERT INTO memories_fts(rowid, content) VALUES (?, ?)",
                             (rid, strip_fts_punctuation(content)))
                conn.execute("INSERT INTO memories_fts_bi(rowid, content) VALUES (?, ?)",
                             (rid, bigram_text(content)))
            if len(rows) < limit:
                set_meta(conn, "fts_text_rules", FTS_TEXT_RULES)
                delete_meta(conn, "fts_text_cursor")
            elif rows:
                set_meta(conn, "fts_text_cursor", rows[-1]["rowid"])
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        if budget is not None:
            budget -= len(rows)
        if len(rows) < limit:
            break

    # --- missing vectors / FTS rows
    remaining = budget
    while remaining is None or remaining > 0:
        n_batch = 200 if remaining is None else min(200, remaining)
        batch = find_unindexed_memories(conn, n_batch)
        if not batch:
            break
        if conn.in_transaction:
            conn.commit()
        vecs = {}
        for r in batch:  # embeddings are computed outside any write transaction (F11)
            if r["no_vec"]:
                try:
                    vecs[r["rowid"]] = embed_passage(r["content"], cfg.get("embed_model"))
                except Exception:  # noqa: BLE001
                    vecs[r["rowid"]] = None
        fixed = 0
        conn.execute("BEGIN IMMEDIATE")
        try:
            for r in batch:
                rid, did = r["rowid"], False
                cur = conn.execute("SELECT id, content FROM memories WHERE rowid=?", (rid,)).fetchone()
                if cur is None or not (cur["id"] == r["id"] and cur["content"] == r["content"]):
                    continue  # deleted, or the rowid now belongs to another record
                if conn.execute("SELECT 1 FROM memories_fts WHERE rowid=?", (rid,)).fetchone() is None:
                    conn.execute("INSERT INTO memories_fts(rowid, content) VALUES (?, ?)",
                                 (rid, strip_fts_punctuation(fts_index_text(r["content"]))))
                    did = True
                if conn.execute("SELECT 1 FROM memories_fts_bi WHERE rowid=?", (rid,)).fetchone() is None:
                    conn.execute("INSERT INTO memories_fts_bi(rowid, content) VALUES (?, ?)",
                                 (rid, bigram_text(fts_index_text(r["content"]))))
                    did = True
                v = vecs.get(rid)
                if v is not None and conn.execute("SELECT 1 FROM memories_vec WHERE rowid=?", (rid,)).fetchone() is None:
                    conn.execute("INSERT INTO memories_vec(rowid, embedding) VALUES (?, ?)",
                                 (rid, serialize_vector(v)))
                    did = True
                fixed += 1 if did else 0
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        changed += fixed
        if remaining is not None:
            remaining -= len(batch)
        if fixed == 0:
            break
    return changed


# ============================================================ FastAPI server

def create_app():
    from fastapi import FastAPI, HTTPException, Request
    from fastapi.responses import JSONResponse
    from pydantic import BaseModel
    from typing import Optional

    class BufferReq(BaseModel):
        content: str = ""
        agent_name: Optional[str] = None
        local_id: Optional[str] = None
        session_id: Optional[str] = None
        turn_id: Optional[str] = None

    class SearchReq(BaseModel):
        query: str = ""
        session_id: Optional[str] = None
        since: Optional[str] = None
        until: Optional[str] = None

    class RepairReq(BaseModel):
        max_records: Optional[int] = None

    class ShutdownReq(BaseModel):
        root: str = ""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if "cfg" not in _SERVER_STATE:
            _SERVER_STATE["cfg"] = get_config()
        _SERVER_STATE.setdefault("session_id", str(uuid.uuid4()))
        yield

    app = FastAPI(lifespan=lifespan)

    @app.middleware("http")
    async def guard(request: Request, call_next):
        if "origin" in request.headers:
            return JSONResponse({"detail": "forbidden (Origin header)"}, status_code=403)
        port = _SERVER_PORT or get_config()["server_port"]
        if request.headers.get("host", "") not in (f"127.0.0.1:{port}", f"localhost:{port}"):
            return JSONResponse({"detail": "forbidden (Host header)"}, status_code=403)
        return await call_next(request)

    def cfg():
        if "cfg" not in _SERVER_STATE:
            _SERVER_STATE["cfg"] = get_config()
        _SERVER_STATE.setdefault("session_id", str(uuid.uuid4()))
        return _SERVER_STATE["cfg"]

    @app.get("/health")
    def health():
        return {"status": "ok", "root": HOME_DIR,
                "code_version": _SERVER_STATE.get("code_version") or _server_code_version(),
                "pid": _os.getpid()}

    @app.post("/buffer")
    def buffer(req: BufferReq):
        c = cfg()
        conn = None
        try:
            conn = _open_db()
            return _store_record(conn, c, req.content, req.agent_name, req.local_id,
                                 req.session_id or _SERVER_STATE["session_id"], req.turn_id)
        except Exception as e:  # noqa: BLE001
            return {"status": "error", "message": f"{type(e).__name__}: {e}"}
        finally:
            if conn:
                conn.close()

    @app.post("/search")
    def search(req: SearchReq):
        c = cfg()
        try:
            since, until = _time_bounds(req.since, req.until)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        conn = _open_db()
        try:
            res = hybrid_search(conn, (req.query or "")[:c["search_query_max_chars"]], c,
                                session_id=req.session_id or _SERVER_STATE["session_id"],
                                since=since, until=until)
        finally:
            conn.close()
        for r in res["results"]:
            r.pop("rowid", None)
            r.pop("_version_group", None)
        return res

    @app.post("/repair")
    def repair(req: Optional[RepairReq] = None):
        c = cfg()
        conn = _open_db()
        try:
            n = _repair(conn, c, req.max_records if req else None)
        finally:
            conn.close()
        return {"status": "ok", "count": n}

    @app.get("/list")
    def list_all():
        conn = _open_db()
        try:
            rows = conn.execute("SELECT id, content, timestamp, agent_name FROM memories ORDER BY rowid").fetchall()
        finally:
            conn.close()
        return {"records": [dict(r) for r in rows], "total": len(rows)}

    @app.post("/shutdown")
    def shutdown(req: ShutdownReq):
        if _norm(req.root or "") != _norm(HOME_DIR):
            raise HTTPException(status_code=403, detail="root mismatch")
        threading.Timer(0.3, _exit_server).start()
        return {"status": "ok"}

    @app.delete("/delete/{memory_id}")
    def delete(memory_id: str):
        raise HTTPException(status_code=403, detail="Pro feature")

    @app.post("/gc")
    def gc(request: Request):
        raise HTTPException(status_code=403, detail="Pro feature")

    @app.post("/import")
    def import_(request: Request):
        raise HTTPException(status_code=403, detail="Pro feature")

    return app


def _remove_own_pid_file():
    """Delete the PID file if it holds this process's PID. The file is closed before it is deleted
    (Windows cannot delete a file that is still open)."""
    try:
        with open(PID_FILE, "r", encoding="utf-8") as f:
            mine = f.read().strip() == str(_os.getpid())
        if mine:
            _os.unlink(PID_FILE)
    except OSError:
        pass


def _exit_server():
    _remove_own_pid_file()
    _os._exit(0)


def cmd_run_server():
    global _SERVER_PORT
    import uvicorn
    cfg = get_config()
    _SERVER_PORT = cfg["server_port"]
    if _get_health(_SERVER_PORT) is not None:
        print(f"N3MC: a memory server already listens on port {_SERVER_PORT}.", file=sys.stderr)
        return 1
    if cfg["bind_host"] != "127.0.0.1":
        print(f"N3MC WARNING: bind_host is {cfg['bind_host']}; the API has no authentication and is reachable "
              "from the network. Use 127.0.0.1.", file=sys.stderr)
    _SERVER_STATE["cfg"] = cfg
    _SERVER_STATE["session_id"] = str(uuid.uuid4())
    _SERVER_STATE["code_version"] = compute_code_version(_CFG_SOURCE)  # same content as cfg (#9)
    conn = _open_db("integrity_check")
    conn.close()
    try:
        _processor.get_model(cfg["embed_model"])  # preload before listening (first run may take minutes)
    except Exception as e:  # noqa: BLE001
        print(f"N3MC: embedding model not loaded ({type(e).__name__}: {e}); continuing without vectors",
              file=sys.stderr)
    try:
        with open(PID_FILE, "x", encoding="utf-8") as f:
            f.write(str(_os.getpid()))
    except FileExistsError:
        try:
            with open(PID_FILE, "w", encoding="utf-8") as f:
                f.write(str(_os.getpid()))
        except OSError:
            pass
    try:
        uvicorn.run(create_app(), host=cfg["bind_host"], port=cfg["server_port"], log_level="error")
    finally:
        _remove_own_pid_file()
    return 0


# ============================================================ HTTP client

def _port():
    return get_config()["server_port"]


def _opener():
    # Never go through a proxy: the server is on 127.0.0.1 (F16).
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _http(method, path, body=None, timeout=HTTP_TIMEOUT, port=None):
    url = f"http://127.0.0.1:{port or _port()}{path}"
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json"} if data is not None else {})
    with _opener().open(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _post(path, body, timeout=HTTP_TIMEOUT, port=None):
    return _http("POST", path, body, timeout, port)


def _get(path, timeout=HTTP_TIMEOUT, port=None):
    return _http("GET", path, None, timeout, port)


def _get_health(port=None):
    try:
        h = _get("/health", timeout=5, port=port)
        return h if isinstance(h, dict) and h.get("status") == "ok" else None
    except Exception:  # noqa: BLE001
        return None


def _health_decision(health):
    if not health:
        return "none"
    if not health.get("root"):
        return "legacy"
    if _norm(health["root"]) != _norm(HOME_DIR):
        return "foreign"
    if health.get("code_version") != compute_code_version():
        return "stale"
    return "ok"


def _request_shutdown(port=None):
    try:
        response = _post("/shutdown", {"root": HOME_DIR}, timeout=5, port=port)
        return isinstance(response, dict) and response.get("status") == "ok"
    except Exception:  # noqa: BLE001
        return False


def _wait_port_free(port=None, seconds=15):
    end = time.time() + seconds
    while time.time() < end:
        if _get_health(port) is None:
            return True
        time.sleep(0.3)
    return False


def _read_pid():
    try:
        with open(PID_FILE, "r", encoding="utf-8") as f:
            return int(f.read().strip())
    except Exception:  # noqa: BLE001
        return None


def _remove_pid_if(pid):
    if _read_pid() == pid:
        try:
            _os.unlink(PID_FILE)
        except OSError:
            pass


def _home_of_env(env):
    h = env.get("N3MC_FREE_CODEX_HOME")
    return _os.path.abspath(_os.path.expanduser(h or _os.path.join("~", ".n3mc-free-codex")))


def _is_own_server_process(pid=None, health=None):
    """True only if psutil confirms the process is this folder's `--run-server`."""
    try:
        import psutil
        if pid is None and health:
            pid = health.get("pid")
        if pid is None:
            port = _port()
            for c in psutil.net_connections(kind="inet"):
                if c.status == "LISTEN" and c.laddr and c.laddr.port == port and c.pid:
                    pid = c.pid
                    break
        if pid is None:
            return False
        p = psutil.Process(int(pid))
        cmd = p.cmdline()
        if "n3memorycore_free_codex.n3memory" not in " ".join(cmd) or "--run-server" not in cmd:
            return False
        return _norm(_home_of_env(p.environ())) == _norm(HOME_DIR)
    except Exception:  # noqa: BLE001
        return False


def _listen_ports(pid):
    try:
        import psutil
        p = psutil.Process(int(pid))
        conns = p.net_connections(kind="inet") if hasattr(p, "net_connections") else p.connections(kind="inet")
        return sorted({c.laddr.port for c in conns if c.status == "LISTEN" and c.laddr})
    except Exception:  # noqa: BLE001
        return []


def _terminate_process(pid):
    try:
        import psutil
        p = psutil.Process(int(pid))
        p.terminate()
        try:
            p.wait(5)
        except Exception:  # noqa: BLE001
            p.kill()
        return True
    except Exception:  # noqa: BLE001
        return False


def _stop_stale_server(health=None):
    """Stop this folder's old server: /shutdown first; kill only after psutil confirms it is ours."""
    port = _port()
    if _request_shutdown():
        return _wait_port_free(port)
    if _is_own_server_process(health=health):
        pid = (health or {}).get("pid")
        if pid and _terminate_process(pid):
            _remove_pid_if(pid)
            return _wait_port_free(port)
    return False


_SERVER_STARTING = False
_SERVER_OK = None


def _foreign(health, unknown=False):
    global _FOREIGN_SERVER_ROOT
    root = health.get("root") if health else None
    _FOREIGN_SERVER_ROOT = root or "(unknown: the server did not report its folder)"
    _notify("port_conflict", f"Another program or N3MC folder ({_FOREIGN_SERVER_ROOT}) is using port {_port()}. "
            f"Records are saved directly and memory search is off. Set a different server_port in {CONFIG_FILE}.")
    return False


def _clear_server_notices():
    for k in ("stale_server", "port_conflict", "server_start_failed"):
        _clear_notice(k)
    try:
        _os.unlink(SERVER_START_FAILED_FILE)
    except OSError:
        pass


PID_RESERVATION_SECONDS = 60


def _reserve_pid_file():
    """Create the PID file, empty, with exclusive creation (review #5). True: reserved by this call;
    False: it exists (another process starts or runs the server); None: it could not be created."""
    try:
        with open(PID_FILE, "x", encoding="utf-8"):
            pass
        return True
    except FileExistsError:
        return False
    except OSError:
        return None


def _drop_reservation():
    """Delete our reservation (still empty: nobody else writes into it)."""
    try:
        if _os.path.getsize(PID_FILE) == 0:
            _os.unlink(PID_FILE)
    except OSError:
        pass


def _write_reserved_pid(pid):
    """Write the child's PID into our (still empty) reservation; never overwrite what is there."""
    try:
        with open(PID_FILE, "r+", encoding="utf-8") as f:
            if not f.read().strip():
                f.seek(0)
                f.write(str(pid))
                f.truncate()
    except OSError:
        pass


def _wait_for_starting_server():
    """Another process is starting this folder's server: poll /health for up to 60 s."""
    global _SERVER_STARTING
    end = time.time() + SERVER_WAIT_SECONDS
    while time.time() < end:
        h = _get_health()
        d = _health_decision(h)
        if d in ("ok", "stale"):
            return True
        if d in ("foreign", "legacy"):
            return _foreign(h)
        time.sleep(0.5)
    _SERVER_STARTING = True
    return False


def _follow_pid_file():
    """"PID file handling" (no server answers). Returns True/False when the PID file decides the outcome,
    or None when there is no live PID file (it was dead and has been removed): start the server."""
    if not _os.path.exists(PID_FILE):
        return None
    pid = _read_pid()
    if pid is None:
        # Empty or unreadable: a start reserved by another process (review #5). Starting for 60 s after
        # the file's modification time, dead afterwards.
        try:
            age = time.time() - _os.path.getmtime(PID_FILE)
        except OSError:
            return None
        if age < PID_RESERVATION_SECONDS:
            return _wait_for_starting_server()
        try:
            if _read_pid() is None and time.time() - _os.path.getmtime(PID_FILE) >= PID_RESERVATION_SECONDS:
                _os.unlink(PID_FILE)
        except OSError:
            pass
        return None
    if _pid_is_own(pid):
        previous_port = _other_server_port(pid)
        if previous_port is not None and _shutdown_other_port(pid, previous_port):
            return _launch()
        return _wait_for_starting_server()
    _remove_pid_if(pid)
    return None


def _start_server():
    global _SERVER_STARTING, _FOREIGN_SERVER_ROOT
    _ensure_dirs()
    for _ in range(3):
        reserved = _reserve_pid_file()
        if reserved is not False:
            break
        r = _follow_pid_file()  # another process starts or runs the server: do not launch
        if r is not None:
            return r
    else:
        return False
    try:
        if _os.path.exists(SERVER_LOG) and _os.path.getsize(SERVER_LOG) > 1024 * 1024:
            open(SERVER_LOG, "wb").close()
        kwargs = {}
        if _os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
        else:
            kwargs["start_new_session"] = True
        with open(SERVER_LOG, "ab") as log:
            proc = subprocess.Popen(
                [*python_cmd(), "-m", "n3memorycore_free_codex.n3memory", "--run-server"],
                stderr=log, stdout=subprocess.DEVNULL, stdin=subprocess.DEVNULL, cwd=_server_cwd(), **kwargs,
            )
    except Exception as e:  # noqa: BLE001
        print(f"N3MC: could not start the memory server ({type(e).__name__}: {e})", file=sys.stderr)
        if reserved:
            _drop_reservation()
        return False
    if reserved:
        _write_reserved_pid(proc.pid)
    end = time.time() + SERVER_WAIT_SECONDS
    while time.time() < end:
        h = _get_health()
        d = _health_decision(h)
        if d in ("ok", "stale"):
            _clear_server_notices()
            return True
        if d in ("foreign", "legacy"):
            _foreign(h)
            return False
        if proc.poll() is not None:
            _notify("server_start_failed", f"The N3MC memory server could not start (exit code {proc.returncode}). "
                    f"See {SERVER_LOG} for the reason.")
            try:
                with open(SERVER_START_FAILED_FILE, "w", encoding="utf-8") as f:
                    f.write(datetime.now(timezone.utc).isoformat())
            except OSError:
                pass
            _remove_pid_if(proc.pid)
            return False
        time.sleep(0.5)
    _SERVER_STARTING = True  # still loading the model
    return False


def _server_cwd():
    checkout = Path(__file__).resolve().parents[1]
    if not sys.flags.isolated and _norm(_os.getcwd()) == _norm(checkout):
        return str(checkout)
    return HOME_DIR


def _launch():
    try:
        if time.time() - _os.path.getmtime(SERVER_START_FAILED_FILE) < 300:
            return False
    except OSError:
        pass
    return _start_server()


def _pid_is_own(pid):
    try:
        import psutil  # noqa: F401
    except ImportError:
        try:
            return time.time() - _os.path.getmtime(PID_FILE) < 60
        except OSError:
            return False
    return _is_own_server_process(pid=pid)


def _other_server_port(pid):
    cur = _port()
    for p in _listen_ports(pid):
        if p == cur:
            continue
        h = _get_health(port=p)
        if h and h.get("root") and _norm(h["root"]) == _norm(HOME_DIR):
            return p
    return None


def _shutdown_other_port(pid, port):
    if not _request_shutdown(port=port) or not _wait_port_free(port):
        return False
    _remove_pid_if(pid)
    return True


def ensure_server():
    """True if this folder's up-to-date server answers; False -> work without a server."""
    global _FOREIGN_SERVER_ROOT, _SERVER_STARTING
    _FOREIGN_SERVER_ROOT = None
    _SERVER_STARTING = False
    h = _get_health()
    d = _health_decision(h)
    if d == "ok":
        _clear_server_notices()
        return True
    if d == "stale":
        if _stop_stale_server(h):
            return _launch()
        _notify("stale_server", "The old memory server could not be stopped. Check the server_port in each "
                "N3MC folder's config.json, then restart it by hand.")
        return True  # same root, same DB: keep using it
    if d == "foreign":
        return _foreign(h)
    if d == "legacy":
        if _is_own_server_process(health=h) and _stop_stale_server(h):
            return _launch()
        return _foreign(h)
    # no server answers
    r = _follow_pid_file()
    if r is not None:
        return r
    return _launch()


def _use_server():
    global _SERVER_OK
    if _SERVER_OK is None:
        try:
            _SERVER_OK = bool(ensure_server())
        except Exception as e:  # noqa: BLE001
            print(f"N3MC: server check failed ({type(e).__name__}: {e})", file=sys.stderr)
            _SERVER_OK = False
    return _SERVER_OK


def _unavailable_reason():
    if _FOREIGN_SERVER_ROOT:
        return f"another N3MC folder's server is using port {_port()}"
    if _SERVER_STARTING:
        return "the memory server is still starting"
    return "the memory server is not running"


# ============================================================ saving / searching

_PROCESS_SESSION_ID = str(uuid.uuid4())


def _env_session():
    return _os.environ.get("N3MC_FREE_CODEX_SESSION_ID") or None


def _buffer_direct(content, agent_name=None, session_id=None, turn_id=None, local_id=None):
    """Save without the server (no embedding; a later --repair adds the vector). Never silent on failure."""
    try:
        conn = _open_db_direct()
        try:
            r = _store_record(conn, get_config(), content, agent_name, local_id,
                              session_id or _env_session() or _PROCESS_SESSION_ID, turn_id, embed=False)
        finally:
            conn.close()
        if r.get("status") == "error":
            raise RuntimeError(r.get("message"))
        _clear_notice("save_failed")
        return r
    except Exception as e:  # noqa: BLE001
        print("⚠️ Physical save failed. Current memories may be lost.", file=sys.stderr)
        _notify("save_failed", f"A record could not be saved ({type(e).__name__}: {e}). Current memories may be "
                "lost; if it happens again, check that no other program holds the memory database.")
        return {"status": "error", "message": f"{type(e).__name__}: {e}"}


def _connection_target(cfg=None):
    cfg = get_config() if cfg is None else cfg
    port = cfg.get("connect_server_port")
    root = cfg.get("connect_server_root")
    if bool(port) != bool(root):
        message = "Set both connect_server_port and connect_server_root; using standalone mode."
        notice = _notices_read().get("connection_incomplete")
        if not isinstance(notice, dict) or notice.get("message") != message:
            _notify("connection_incomplete", message)
    else:
        _clear_notice("connection_incomplete")
    return (port, root) if port and root else None


def _verified_target(target):
    port, expected_root = target
    health = _get_health(port)
    root = health.get("root") if health else None
    return (isinstance(root, str) and _os.path.isabs(root)
            and _norm(root) == _norm(expected_root))


def _save_record(content, agent_name=None, session_id=None, turn_id=None, local_id=None, project=None):
    cfg = get_config()
    target = _connection_target(cfg)
    if target:
        body = {"content": content, "agent_name": AGENT_NAME if agent_name is None else agent_name,
                "local_id": local_id or cfg["local_id"]}
        for key, value in (("session_id", session_id), ("turn_id", turn_id), ("project", project)):
            if value is not None:
                body[key] = value
        try:
            if not _verified_target(target):
                raise ValueError("configured server could not be verified")
            result = _post("/buffer", body, port=target[0])
            if not isinstance(result, dict) or result.get("status") not in ("ok", "skipped"):
                raise ValueError("server did not confirm save")
            return result
        except Exception as exc:
            return {"status": "error", "message": f"Connected save failed ({type(exc).__name__}); no local DB fallback."}
    if _use_server():
        body = {"content": content}
        for k, v in (("agent_name", agent_name), ("session_id", session_id), ("turn_id", turn_id),
                     ("local_id", local_id)):
            if v is not None:
                body[k] = v
        try:
            r = _post("/buffer", body)
            if isinstance(r, dict) and r.get("status") in ("ok", "skipped"):
                _clear_notice("save_failed")  # any save that ends ok / skipped clears it (2026-11-22, F2)
                return r
        except Exception as e:  # noqa: BLE001
            print(f"N3MC: server save failed ({type(e).__name__}); saving directly", file=sys.stderr)
    return _buffer_direct(content, agent_name, session_id, turn_id, local_id)


def _save_text(role, text, turn_id, session_id=None, project=None):
    """Purify the whole message, chunk it, tag the chunks and save each. Returns (saved, failed)."""
    text = purify_text(text or "")
    if not text.strip():
        return 0, 0
    saved = failed = 0
    for rec in add_chunk_prefixes(role, chunk_text(text, 400, 40)):
        r = _save_record(rec, AGENT_NAME, session_id, turn_id, project=project)
        if r.get("status") == "ok":
            saved += 1
        elif r.get("status") == "error":
            failed += 1
    return saved, failed


def _placeholder(body_line, notices):
    out = ["# Recalled Memory Context", ""]
    for n in notices:
        out += [f"> ⚠️ N3MC notice: {n}", ""]
    out += [body_line, ""]
    return "\n".join(out)


def _valid_search_hit(row):
    if not isinstance(row, dict) or not isinstance(row.get("content"), str):
        return False
    score = row.get("score")
    try:
        return (isinstance(row.get("timestamp"), str)
                and type(score) in (int, float) and math.isfinite(score))
    except OverflowError:
        return False


def _search_exchanges(response, notices):
    raw_pairs = response.get("pairs")
    raw_omitted = response.get("pairs_omitted")
    malformed = False
    pairs, omitted = {}, {}
    if isinstance(raw_pairs, dict):
        for turn, chunks in raw_pairs.items():
            if not isinstance(chunks, list):
                malformed = True
                continue
            valid = [chunk for chunk in chunks if isinstance(chunk, dict)
                     and isinstance(chunk.get("content"), str)]
            malformed |= len(valid) != len(chunks)
            if valid:
                pairs[turn] = valid
    elif raw_pairs is not None:
        malformed = True

    if isinstance(raw_omitted, dict):
        for turn, count in raw_omitted.items():
            if type(count) is not int or count < 0:
                malformed = True
            elif count:
                omitted[turn] = count
    elif raw_omitted is not None:
        malformed = True

    if malformed:
        notices.append("Supplementary exchanges could not be displayed in full.")
    return pairs, omitted


def _search_text(query, session_id=None, since=None, until=None, *, cfg=None):
    cfg = get_config() if cfg is None else cfg
    query = sanitize_surrogates(query or "")[:cfg["search_query_max_chars"]]
    target = _connection_target(cfg)
    notices = _take_notices()
    if not query.strip():
        return _placeholder("_No relevant memories found._", notices)
    port = None
    if target:
        port = target[0]
        if not _verified_target(target):
            return _placeholder("_(memory search unavailable: the configured server could not be verified)_", notices)
    elif not _use_server():
        return _placeholder(f"_(memory search unavailable: {_unavailable_reason()})_", notices)
    body = {"query": query}
    if session_id:
        body["session_id"] = session_id
    if since:
        body["since"] = since
    if until:
        body["until"] = until
    try:
        r = _post("/search", body, port=port) if port else _post("/search", body)
        if not isinstance(r, dict) or not isinstance(r.get("results"), list):
            raise ValueError("invalid search response")
        results = [row for row in r["results"] if _valid_search_hit(row)]
        if len(results) != len(r["results"]):
            if not results:
                raise ValueError("no valid ranked search results")
            notices.append("Some ranked search results could not be displayed.")
        pairs, omitted = _search_exchanges(r, notices)
        context = render_memory_context(query, results, pairs, omitted, notices, connected=bool(target))
        return sanitize_surrogates(context)
    except Exception as e:  # noqa: BLE001
        print(f"N3MC: search failed ({type(e).__name__}).", file=sys.stderr)
        return _placeholder(f"_(memory search unavailable: {type(e).__name__})_", notices)


# ============================================================ hook helpers

def _read_stdin_text():
    raw = getattr(sys.stdin, "buffer", None)
    return sys.stdin.read() if raw is None else raw.read().decode("utf-8")


def _housekeeping():
    now = time.time()
    try:
        for name in _os.listdir(MEMORY_DIR):
            if re.fullmatch(r"skip_[0-9a-f]{64}", name):
                path = _os.path.join(MEMORY_DIR, name)
                try:
                    if now - _os.path.getmtime(path) > 30 * 86400:
                        _os.unlink(path)
                except FileNotFoundError:
                    pass
        if _os.path.exists(AUDIT_LOG) and _os.path.getsize(AUDIT_LOG) > AUDIT_ROTATE_BYTES:
            _os.replace(AUDIT_LOG, AUDIT_LOG + ".1")
    except FileNotFoundError:
        pass
    except OSError as exc:
        print(f"N3MC: housekeeping failed ({exc})", file=sys.stderr)


def cmd_stop():
    _housekeeping()
    return 0


def cmd_init():
    from .codex_install import install

    get_config()
    if not _connection_target():
        _open_db().close()
    return install()


# ============================================================ read-only commands

def _fmt_line(r):
    agent = r.get("agent_name")
    fields = (r["id"], r["timestamp"], "-" if agent is None else agent, (r["content"] or "")[:80])
    return "\t".join(re.sub(r"[\r\n\t]", " ", field) for field in fields)


def _bounds(since, until):
    try:
        return _time_bounds(since, until)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return None


def cmd_list(since=None, until=None, fmt="text"):
    b = _bounds(since, until)
    if b is None:
        return 2
    conn = _read_db_if_exists()
    if conn is None:
        print(f"No DB found at {DB_PATH}", file=sys.stderr)
        print("Total: 0 records", file=sys.stderr if fmt == "jsonl" else sys.stdout)
        return 0
    try:
        rows = _database.get_all_memories(conn, b[0], b[1])
    finally:
        conn.close()
    for r in rows:
        if fmt == "jsonl":
            print(json.dumps({k: r.get(k) for k in ("id", "timestamp", "agent_name", "content",
                                                               "session_id", "turn_id", "owner_id", "local_id")},
                             ensure_ascii=False))
        else:
            print(_fmt_line(r))
    print(f"Total: {len(rows)} records", file=sys.stderr if fmt == "jsonl" else sys.stdout)
    return 0


def cmd_recall_thread(turn_id, before=2, after=2, fmt="text"):
    totals = sys.stderr if fmt == "jsonl" else sys.stdout
    conn = _read_db_if_exists()
    if conn is None:
        print(f"No DB found at {DB_PATH}", file=sys.stderr)
        print("Total: 0 records", file=totals)
        return 0
    try:
        columns = {r["name"] for r in conn.execute("PRAGMA table_info(memories)")}
        if "turn_id" not in columns:
            print("Total: 0 records", file=totals)
            return 0
        anchor = conn.execute(
            "SELECT MIN(rowid) AS lo, MAX(rowid) AS hi FROM memories WHERE turn_id=?", (turn_id,)
        ).fetchone()
        if anchor["lo"] is None:
            print("Total: 0 records", file=totals)
            return 0
        session = conn.execute(
            "SELECT session_id FROM memories WHERE rowid=?", (anchor["lo"],)
        ).fetchone()["session_id"] if "session_id" in columns else None
        turns = [turn_id]
        if session:
            same_session_bounds = """
                WITH turns AS (
                    SELECT turn_id, MIN(rowid) AS lo, MAX(rowid) AS hi
                    FROM memories WHERE turn_id IS NOT NULL AND turn_id != ?
                    GROUP BY turn_id
                )
                SELECT turns.turn_id FROM turns JOIN memories AS first ON first.rowid = turns.lo
                WHERE first.session_id = ?
            """
            # SQLite LIMIT parameters must fit a signed 64-bit integer.
            max_limit = (1 << 63) - 1
            previous = conn.execute(same_session_bounds + " AND hi < ? ORDER BY hi DESC LIMIT ?",
                                    (turn_id, session, anchor["lo"], min(max_limit, max(0, before))))
            turns.extend(row[0] for row in previous)
            following = conn.execute(same_session_bounds + " AND lo > ? ORDER BY lo ASC LIMIT ?",
                                     (turn_id, session, anchor["hi"], min(max_limit, max(0, after))))
            turns.extend(row[0] for row in following)
        q = ",".join("?" * len(turns))
        rows = [dict(row) for row in conn.execute(
            f"SELECT * FROM memories WHERE turn_id IN ({q}) ORDER BY rowid", turns
        )]
    finally:
        conn.close()
    for r in rows:
        if fmt == "jsonl":
            print(json.dumps({k: r.get(k) for k in ("id", "timestamp", "agent_name", "turn_id", "content")},
                             ensure_ascii=False))
        else:
            print(_fmt_line(r))
    print(f"Total: {len(rows)} records", file=totals)
    return 0


def cmd_show_turn(turn_id):
    conn = _read_db_if_exists()
    if conn is None:
        print(f"No DB found at {DB_PATH}", file=sys.stderr)
        rows = []
    else:
        try:
            columns = {r["name"] for r in conn.execute("PRAGMA table_info(memories)")}
            rows = get_memories_by_turn_id(conn, turn_id) if "turn_id" in columns else []
        finally:
            conn.close()
    rows.sort(key=lambda r: 0 if r["content"].startswith("[user") else 1)
    for r in rows:
        print(f"--- {r['id']} saved={_processor._fmt_saved(r['timestamp'])} ---")
        print(r["content"])
    print(f"Total: {len(rows)} records")
    return 0


# ============================================================ --buffer / --search / --repair / --reembed

def cmd_buffer(text, agent_id=None):
    if text == "-":
        try:
            text = _read_stdin_text()
        except UnicodeDecodeError:
            print("N3MC: --buffer: stdin must be valid UTF-8.", file=sys.stderr)
            return 1
    text = sanitize_surrogates(text or "")
    if not text.strip():
        print("Skipped (empty).")
        return 0
    r = _save_record(text, agent_id, _env_session())
    if r.get("status") == "ok":
        print("Saved 1 record.")
        return 0
    if r.get("status") == "skipped":
        print(f"Skipped ({r.get('reason')}).")
        return 0
    print(r.get("message", "N3MC: record could not be saved."), file=sys.stderr)
    return 1


def cmd_search(query, since=None, until=None):
    b = _bounds(since, until)
    if b is None:
        return 2
    out = _search_text(sanitize_surrogates(query or ""), _env_session(), b[0], b[1])
    sys.stdout.write(out if out.endswith("\n") else out + "\n")
    return 0


def cmd_repair():
    if _connection_target():
        print("N3MC: --repair requires standalone mode.", file=sys.stderr)
        return 1
    if not _use_server():
        print(f"N3MC: --repair skipped ({_unavailable_reason()})", file=sys.stderr)
        return 0
    try:
        r = _post("/repair", {}, timeout=600)
        if not isinstance(r, dict) or r.get("status") != "ok":
            raise ValueError("server did not confirm repair")
        n = r.get("count")
        if type(n) is not int or n < 0:
            raise ValueError("invalid repair count")
    except Exception as e:  # noqa: BLE001
        print(f"N3MC: repair failed ({type(e).__name__}: {e})", file=sys.stderr)
        return 1
    if n:
        print(f"Repaired {n} record(s).")
    return 0


def cmd_reembed():
    cfg = get_config()
    if _connection_target(cfg):
        print("N3MC: --reembed requires standalone mode.", file=sys.stderr)
        return 1
    model = cfg["embed_model"]
    try:
        _processor.get_model(model)
        test = embed_passage("dimension probe", model)
    except Exception as e:  # noqa: BLE001
        print(f"N3MC: --reembed: could not load {model} ({type(e).__name__}: {e})", file=sys.stderr)
        return 1
    current = _read_db_if_exists()
    dim = _database.EMBED_DIM  # creation default, used only if there is no vector table yet
    if current is not None:
        try:
            if current.execute("SELECT 1 FROM sqlite_master WHERE name='memories_vec'").fetchone():
                dim = vec_dim(current)
        finally:
            current.close()
    if dim is None:
        print("N3MC: --reembed: could not read the dimension of memories_vec from its table definition.",
              file=sys.stderr)
        return 1
    if len(test) != dim:
        print(f"N3MC: --reembed: {model} makes {len(test)}-dimensional vectors but memories_vec has {dim}; "
              "a different dimension needs the manual procedure in §3 \"Embeddings\".", file=sys.stderr)
        return 1

    h = _get_health()
    if h and h.get("root") and _norm(h["root"]) == _norm(HOME_DIR):
        stopped = _stop_stale_server(h)
    else:
        pid = _read_pid()
        previous_port = _other_server_port(pid) if pid is not None and _is_own_server_process(pid=pid) else None
        stopped = previous_port is None or _shutdown_other_port(pid, previous_port)
    if not stopped:
        print("N3MC: --reembed: could not stop the local memory server.", file=sys.stderr)
        return 1
    conn = _open_db()
    try:
        if vec_dim(conn) != dim:
            print("N3MC: --reembed: vector table changed during preflight.", file=sys.stderr)
            return 1
        total = count_memories(conn)
        cursor = 0
        if get_meta(conn, "reembed_model") == model:
            try:
                cursor = int(get_meta(conn, "reembed_cursor", 0))
                if not 0 <= cursor < 1 << 63:
                    raise ValueError("cursor outside SQLite rowid range")
            except ValueError:
                print("N3MC: --reembed: invalid reembed_cursor in database metadata.", file=sys.stderr)
                return 1
        else:
            set_meta(conn, "reembed_model", model)
            set_meta(conn, "reembed_cursor", 0)
            conn.commit()
        done = conn.execute("SELECT COUNT(*) FROM memories WHERE rowid <= ?", (cursor,)).fetchone()[0]
        while True:
            rows = conn.execute("SELECT rowid AS rid, content FROM memories WHERE rowid > ? ORDER BY rowid LIMIT 200",
                                (cursor,)).fetchall()
            if not rows:
                break
            try:
                vecs = [embed_passage(r["content"], model) for r in rows]
            except Exception as exc:
                print(f"N3MC: --reembed: embedding failed ({type(exc).__name__}: {exc}). "
                      "Run --reembed again to resume.", file=sys.stderr)
                return 1
            if conn.in_transaction:
                conn.commit()
            conn.execute("BEGIN IMMEDIATE")
            try:
                for r, v in zip(rows, vecs):
                    conn.execute("DELETE FROM memories_vec WHERE rowid=?", (r["rid"],))
                    conn.execute("INSERT INTO memories_vec(rowid, embedding) VALUES (?, ?)",
                                 (r["rid"], serialize_vector(v)))
                cursor = rows[-1]["rid"]
                set_meta(conn, "reembed_cursor", cursor)
                conn.commit()
            except BaseException:
                conn.rollback()
                raise
            done += len(rows)
            print(f"Re-embedded {done} / {total}", file=sys.stderr)
        set_meta(conn, "embed_model", model)
        set_meta(conn, "embed_dim", dim)
        set_meta(conn, "embed_model_at", datetime.now(timezone.utc).isoformat())
        delete_meta(conn, "reembed_model")
        delete_meta(conn, "reembed_cursor")
        conn.commit()
    finally:
        conn.close()
    _clear_notice("embed_model_mismatch")
    print(f"Re-embedded {total} record(s) with {model}.")
    return 0


# ============================================================ main

def build_parser():
    p = argparse.ArgumentParser(prog="n3mc-free-codex", description="N3MemoryCore (Free): persistent memory for Codex")
    g = p.add_argument_group("commands").add_mutually_exclusive_group()
    g.add_argument("--init", action="store_true", help="create ~/.n3mc-free-codex and register the Codex hooks")
    g.add_argument("--buffer", metavar="TEXT", help="save text ('-' reads stdin)")
    g.add_argument("--search", metavar="QUERY", help="search memories")
    g.add_argument("--list", action="store_true", help="list records")
    g.add_argument("--recall-thread", metavar="TURN_ID", help="show the turns around a turn_id")
    g.add_argument("--show-turn", metavar="TURN_ID", help="show the full text of one exchange")
    g.add_argument("--repair", action="store_true", help="index records that lack vectors / FTS rows")
    g.add_argument("--reembed", action="store_true", help="re-embed all records with the configured model")
    g.add_argument("--stop", action="store_true", help="session-end clean-up (does not stop the server)")
    g.add_argument("--hook-submit", action="store_true", help=argparse.SUPPRESS)
    g.add_argument("--save-claude-turn", action="store_true", help=argparse.SUPPRESS)
    g.add_argument("--run-server", action="store_true", help=argparse.SUPPRESS)
    o = p.add_argument_group("options")
    o.add_argument("--agent-id", metavar="NAME", help="agent_name for --buffer")
    o.add_argument("--since", metavar="DATE")
    o.add_argument("--until", metavar="DATE")
    o.add_argument("--before", type=int)
    o.add_argument("--after", type=int)
    o.add_argument("--format", choices=("text", "jsonl"))
    return p


def main(argv=None):
    _reconfigure_streams()
    parser = build_parser()
    args = parser.parse_args(argv)
    if (args.since is not None or args.until is not None) and args.search is None and not args.list:
        parser.error("--since and --until require --search or --list")
    if args.agent_id is not None and args.buffer is None:
        parser.error("--agent-id requires --buffer")
    if (args.before is not None or args.after is not None) and args.recall_thread is None:
        parser.error("--before and --after require --recall-thread")
    if args.format is not None and not args.list and args.recall_thread is None:
        parser.error("--format requires --list or --recall-thread")
    if args.show_turn == "" or args.recall_thread == "":
        parser.error("turn ID must not be empty")
    try:
        if args.run_server:
            return cmd_run_server()
        if args.hook_submit or args.save_claude_turn:
            from .codex_entry import prompt_main, stop_main

            return prompt_main() if args.hook_submit else stop_main()
        if args.stop:
            return cmd_stop()
        if args.init:
            return cmd_init()
        if args.reembed:
            return cmd_reembed()
        if args.repair:
            return cmd_repair()
        if args.buffer is not None:
            return cmd_buffer(args.buffer, args.agent_id)
        if args.search is not None:
            return cmd_search(args.search, args.since, args.until)
        if args.list:
            return cmd_list(args.since, args.until, args.format or "text")
        if args.recall_thread:
            before = 2 if args.before is None else args.before
            after = 2 if args.after is None else args.after
            return cmd_recall_thread(args.recall_thread, before, after, args.format or "text")
        if args.show_turn:
            return cmd_show_turn(args.show_turn)
    except KeyboardInterrupt:
        return 130
    except (OSError, sqlite3.Error) as exc:
        print(f"N3MC: {exc}", file=sys.stderr)
        return 1
    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
