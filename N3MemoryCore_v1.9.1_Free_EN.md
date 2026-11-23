# N3MemoryCore Free for Codex v1.9.1

[日本語](N3MemoryCore_v1.9.1_Free_JP.md)

Build persistent conversation memory for local Codex. Use **Sol** for implementation and debugging and **Astra** for code review. Choose an available model explicitly.

## 1. Setup and regeneration

1. Use a dedicated directory with Python 3.10 or newer. For a rebuild, back up the source and uncommitted work before replacing the package. Keep personal memory data and Codex settings outside the source tree.
2. To regenerate, give Codex this document and request an implementation in that directory. For the reference implementation, use the existing repository. In either case, install from the source tree with `python -m pip install -e ".[test]"`.
3. First verify the build with temporary `N3MC_HOME` and `N3MC_CODEX_HOOKS_PATH` values and a free loopback port. Run the checks in §6.
4. To activate local Codex, the implementing Codex agent installs the package in the Python environment the user will keep, runs `n3mc --init` there, and verifies both hook registrations. After successful registration, show the user the destination and the `UserPromptSubmit` and `Stop` commands. The user's only manual setup action is to review and trust both handlers in desktop **Settings → Hooks** or CLI `/hooks`. Do not trust them on the user's behalf or skip this step. After approval, Codex automatically runs the autonomous evaluation in §6 (including the live checks in §§6.1–6.2) and pytest in §7, then reports the results. Do not claim capture works until it has been checked.

## 2. Package and data

- Distribution `n3memorycore-free-codex`, version `1.9.1`. Use setuptools. Runtime dependencies are `fastapi`, `uvicorn`, `pydantic`, `sqlite-vec`, `sentence-transformers`, `uuid7`, and `psutil`. Test extras are `pytest` and `httpx`.
- Under `n3memorycore/` put `n3memory.py` (CLI and server), `paths.py`, `codex_entry.py`, `codex_install.py`, `maintenance.py` and `core/{database,processor}.py`. Include tests, `pyproject.toml`, `AGENTS.md`, both README files and both specifications.
- Console targets are `n3mc → n3memorycore.n3memory:main`, `n3mc-hook → n3memorycore.codex_entry:prompt_main`, and `n3mc-stop-hook → n3memorycore.codex_entry:stop_main`.
- The data root defaults to `~/.n3mc` and can be overridden with `N3MC_HOME`. Back up `config.json` and `.memory/n3memory.db` together. Use SQLite's online backup or stop the matching server before copying the database. Preserve existing ownership IDs, schema, and index metadata.
- Replace fenced code with `[code omitted]`. Split on paragraphs, sentences, then bounded windows of 400 characters with 40-character overlap. Store every resulting chunk. Keep `[user]` and `[claude]` as stored role prefixes for backward compatibility. Record the source as `agent_name=codex`.
- The default CPU model is `intfloat/multilingual-e5-base` (768 dimensions). A cold start may download the weights. Persist text during a model outage, and use FTS and deferred index repair as specified below.
- Codex defaults are `min_score=0.2`, `min_results=0`, and `context_max_chars=12000`. Set `semantic_rescue_enabled=true`, `semantic_rescue_min_cos=0.80`, and `semantic_rescue_margin=0.02`. These values take precedence over the inherited backend defaults below.


## ⚠️ Disclaimer & Distribution Terms

This software and specification are provided **"AS-IS"** without warranty of any kind.

- **No Support**: The author provides no bug fixes, answers to questions, or guarantees of operation.
- **No Warranty / No Liability**: The author shall not be liable for any damages arising from use of this software, including but not limited to data loss, business interruption, or third-party claims.
- **Use at Your Own Risk**: You assume full responsibility for your use of this software.
- **Right to Change**: The author may modify or discontinue this software at any time without notice.

By using this software, you agree to the terms above.

- **License**: Apache License 2.0. See the LICENSE file for details.

> **Removal (Uninstall)**: To remove N3MemoryCore, do not delete the folder directly. Instead, ask Codex: "Please delete N3MemoryCore." This ensures the hook configuration is also properly removed.
> **Backup before removal**: To carry over your memories, save the following two files before deletion: `n3memory.db` (memory data) and `config.json` (contains the `owner_id` and `local_id` UUIDv4 keys). These must be kept together — without the matching keys, owner verification and environment classification will not function correctly.

> **For implementation questions**: While the author cannot be contacted for support, you can load this specification into Codex and ask questions directly — Codex can assist with implementation and customization.
> **For customization**: When customizing N3MemoryCore, tell Codex where this specification file is and say "Please update the specification too." This specification itself was created that way.

---

## 3. Technical Specifications (No Modifications Allowed)

> **⚠️ AI must not auto-modify**: AI must not autonomously change any of the following specifications for speed improvement or optimization. Changes to the embedding model, vector dimensions, or synchronous write settings are only permitted by a human manually editing `config.json`.

### ID Hierarchy

N3MemoryCore uses 6 ID fields to identify the origin and context of each record:

| ID | Stored in | Generated | Granularity | Purpose |
|---|---|---|---|---|
| `id` (PK) | DB record | Per record (UUIDv7, time-ordered) | **One record** | Unique identifier for each memory — used for deletion and dedup |
| `owner_id` | `config.json` | First startup (UUIDv4) | **Owner / N3MC server** | Identifies the N3MC FastAPI instance / data owner — used for shared/multi-user scenarios and import provenance |
| `session_id` | Supplied by host (hook stdin JSON) or in-memory fallback | Per conversation | **Task / project / conversation** | Groups memories that belong to one task, project, or conversation thread so they surface together. Codex supplies a `session_id` field (its conversation session ID) in the UserPromptSubmit / Stop hook stdin JSON; the hook forwards it to `/buffer` and `/search`. Other hosts can pass their own identifier the same way (n3memory-lite task numbers, an Ollama-style chat picker, etc.). When the host does not supply a `session_id` — or for direct CLI calls outside a hook — fall back to a UUIDv4 generated at `n3memory.py` startup (per-process). Drives the `b_session` ranking bias in Free and Pro |
| `local_id` | `config.json` / API | First startup (UUIDv4), or per request | **Agent / install** | UUIDv4 identifier for the speaking agent (one Codex install = one `local_id`; different agents on the same DB get different UUIDs). Stored on every record. **In Free, `b_local` is unused (always 1.0)** — the per-agent ranking multiplier is a Pro feature; see "Search ranking bias" below |
| `turn_id` | Codex hook input | Per turn | Share it between the prompt and reply. A manual save can have NULL |
| `agent_name` | DB record | Per buffer call (free-form string) | **Agent display name** | Human-readable label for the agent (e.g. `"codex"`). The `--buffer --agent-id <name>` option sets **this** field (the option name is kept for compatibility, §3.7); it never sets `local_id` |

**Hierarchy relationship:**

```
owner_id  (the data folder ~/.n3mc and its owner: config.json, first startup)
  └── local_id  (the install: config.json, first startup; the same in every session)
        └── session_id  (one Codex conversation, from the hook; else a per-process UUIDv4)
              └── turn_id  (one exchange: one user message and the reply to it)
                    └── id  (one record = one chunk, UUIDv7)

agent_name  (a display label, outside the hierarchy: "codex" for the hooks)
```

`local_id` is not a per-session agent: it is written to `config.json` once, and the hooks and the CLI never send one, so every record of an install carries the same value (an API client may pass its own `local_id` per request). A long message becomes several `id` records that share one `turn_id`. In Free, one install has one DB, so `owner_id` and `local_id` each keep one value; they tell records apart only when records from another DB are brought in (Pro).

**Search ranking bias (Free edition):**
- `session_id` match → `b_session = 1.0` (mismatch or NULL: `0.6`) — **groups conversation by task / project**, so memories from the ongoing exchange rank above unrelated past sessions. This is Free's primary ranking signal beyond similarity and freshness.
- `local_id` — stored but **not used in Free edition ranking**. Local bias (`b_local`) is a Pro feature; in Free, `b_local` is always 1.0 regardless of match/mismatch. The Pro edition applies `b_local = 1.0` on match and `b_local = 0.8` on mismatch to additionally prioritize the agent's own memories over those from other agents on the same DB.

### Embeddings
- **Default model**: `intfloat/multilingual-e5-base` / Vector: float[768]
- The default is multilingual on purpose — it indexes Japanese, English, Chinese, Korean, and ~100 other languages out of the box. Users who need higher precision in a single language can override the model (see "Switching to a language-specialised model" below); the default release does NOT make that decision for them.
- Always specify `normalize_embeddings=True` at retrieval time to guarantee L2-normalized vectors (norm=1).
- **Input Prefixes (Required)**: Without prefixes, this model's accuracy degrades significantly. The following must be strictly observed:

```python
# At save time (registering as a document)
text_to_embed = "passage: " + content

# At search time (matching as a query)
text_to_embed = "query: " + keyword
```

#### Switching to a language-specialised model (user-side customisation)

The embedding model is the `embed_model` field in `~/.n3mc/config.json` (default `intfloat/multilingual-e5-base`, written into the file on first start). There is **no environment-variable override** (v1.5.0): `config.json` always contains `embed_model`, so the `$N3MC_EMBED_MODEL` variable that earlier versions documented never took effect, and §3 allows the model to be changed only by a human editing `config.json`.

**Load failures (v1.5.0)**: if the model cannot be loaded (offline first start, no Hugging Face cache, a misspelled `embed_model`), do not retry the load on every save and search. After a failure, `get_model()` raises immediately without trying again for 60 seconds (`MODEL_RETRY_SECONDS`), so saves fall back to records without vectors (re-indexed by a later `--repair`) and searches run keyword-only with the `embed_query` warning (§5) instead of each waiting for a download attempt. Print one line to stderr per failed attempt (at most once a minute).

Examples a user might configure:

| Goal | `embed_model` value | Vector dim |
|---|---|---|
| English-only, slightly higher precision | `intfloat/e5-base-v2` | 768 |
| Multilingual, higher precision (slower, larger) | `intfloat/multilingual-e5-large` | 1024 |
| Japanese-specialised | `cl-nagoya/sup-simcse-ja-base` | 768 |
| English, smaller / faster | `intfloat/e5-small-v2` | 384 |

**⚠️ Vector dimension constraint**: `memories_vec` is created with a fixed `float[768]` dimension. Switching to a model with a different vector size requires dropping and recreating the vec table (and re-embedding every record). The reference implementation only supports same-dimension switches without manual intervention.

**Upgrade procedure (same-dimension model swap)**:
1. Edit `~/.n3mc/config.json` → set `embed_model` to the new model name.
2. Restart the server (stop it the way `_stop_stale_server` does — §3; never by the bare number in the PID file — or just let the next CLI call relaunch it).
3. The next `/repair` detects the model mismatch (`meta.embed_model`, §3.5 "Index metadata") and shows the notice `embed_model_mismatch`. The stored vectors are still from the OLD model, so search quality is degraded until they are re-made.
4. Run `n3mc --reembed`: it re-embeds every record with the new model (resumable; §3.5). Deleting a marker and running `n3mc --repair` does **not** re-make vectors: `--repair` only adds missing ones.

**⚠️ Different-dimension model swap**: NOT supported by the reference implementation without manual SQL. Drop the `memories_vec` table, recreate it with the new dimension, delete the `embed_model`, `embed_dim` and `embed_model_at` rows of `meta`, then run `n3mc --reembed`. (`--reembed` on its own refuses a model whose dimension differs from the table's.)

### Inter-module Imports
Use proper package-relative imports (no `sys.path` hacks). Inside the package:

```python
# n3memorycore/core/processor.py
from .database import (
    get_connection,
    init_db,
    insert_memory,
    search_vector,
    search_fts,
    get_all_memories,
    delete_memory,
    count_memories,
    check_exact_duplicate,
    find_unindexed_memories,
    serialize_vector,        # Required for /repair endpoint
    get_memories_by_turn_id, # Required for Q-A pairing
    strip_fts_punctuation,   # Required for /repair FTS migration
)
```

```python
# n3memorycore/n3memory.py
from .paths import HOME_DIR, MEMORY_DIR, DB_PATH, PID_FILE, AUDIT_LOG, CONFIG_FILE, NOTICES_FILE
from .core.database import (
    get_connection, init_db, migrate_schema, insert_memory, insert_memory_once,
    check_exact_duplicate, search_vector, find_unindexed_memories,
    strip_fts_punctuation, serialize_vector,
)
from .core.processor import (
    embed_passage, cosine_sim_from_l2, hybrid_search,
    purify_text, render_memory_context,
)
```



### Resident FastAPI Server
- **Port**: Default `18520` (configurable via `server_port` in `config.json`). When running another N3MC (e.g. the Pro edition) on the same PC, give each data folder its own `server_port`.
- **Bind address**: `bind_host` (default `127.0.0.1`). **Keep the default.** The server API (search, list, `/shutdown`, etc.) has no authentication, so any other value exposes it to the network. If a value other than `127.0.0.1` is configured, print a warning to stderr at startup.
- **Start Timing**: On execution of any `n3mc` subcommand (or `python -m n3memorycore.n3memory`), follow "Server check and replacement (`ensure_server`)" below and, if needed, automatically start the server in the background as `python -m n3memorycore.n3memory --run-server`. Write the PID file using an atomic operation (e.g., `open(..., 'x')` exclusive-create flag) to prevent duplicate launches when multiple processes check simultaneously.
- **Communication**: HTTP over TCP (`http://127.0.0.1:{port}`). **Never through a proxy** (final review of 2026-11-18, F16): `_post` / `_get` open their requests with `urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=…)`, not `urllib.request.urlopen`. The default opener follows `HTTP_PROXY` and the system proxy settings: with a proxy and no `NO_PROXY` entry for `127.0.0.1` (common on company PCs), every request went to the proxy, the server looked down, each hook waited for the server start, the search said "still starting" and saves went in directly without a vector.
- **Host header check (v1.5.0)**: every endpoint returns 403 unless the request's `Host` header is `127.0.0.1:<port>` or `localhost:<port>`. A web page in the user's browser can otherwise reach the server through DNS rebinding (a name that resolves to 127.0.0.1) and read `GET /list`. The CLI always sends `Host: 127.0.0.1:<port>`; FastAPI's `TestClient` sends `testserver`, so tests set the header explicitly or replace the check. **`<port>` is the port this server process listens on** (the `server_port` it read at start), not the value `config.json` holds now: after the user changes `server_port`, the old server must still answer `/health` and `/shutdown` on its own port so the CLI can stop it ("PID file handling" below).
- **Requests with an `Origin` header are refused (v1.9.1)**: every endpoint returns 403 when the request carries an `Origin` header, whatever its value (`null` included). Requests without it still go through the `Host` check above. A browser adds `Origin` to the requests a web page sends to another site (`fetch`, a form POST). The server listens on `127.0.0.1` without authentication, so a page the user opens can send requests to it, and the `Host` check does not stop them: their `Host` is `127.0.0.1:<port>`. The CLI, the hooks and the tests' clients never send `Origin`, so nothing they do changes. Make this check in the same place as the `Host` check, before any endpoint runs.
- **Endpoints do not block the event loop (v1.5.0)**: define the endpoints that embed or touch the DB (`/buffer`, `/search`, `/repair`, `/list`) with plain `def`, not `async def`, so FastAPI runs them in its thread pool and `/health` keeps answering during a long `/repair`. (In v1.4.0 they were `async def` with synchronous work inside; a long `/repair` made `/health` time out, the CLI concluded there was no server, and fell into the start/replace path.) The SQLite connection used by an endpoint is opened inside that endpoint call (one connection per request), never shared across threads.
- **Health Monitoring**: On every CLI execution, PING the `/health` endpoint and use the response to decide whether the server is our own and running the latest code (see below).

#### Server identity (`/health`)

`GET /health` returns:

```json
{"status": "ok", "root": "<absolute path of HOME_DIR>", "code_version": "<16 hex chars>", "pid": 12345}
```

- `root`: absolute path of the server's data folder (`$N3MC_HOME` or `~/.n3mc`). Compare with `os.path.normcase(os.path.abspath(...))`.
- `code_version`: first 16 hex chars of a SHA-256 over the file contents of `n3memorycore/n3memory.py`, `core/database.py`, `core/processor.py`, and the contents of `config.json` (if it parses as JSON, the key-sorted `json.dumps(..., sort_keys=True)`; otherwise the raw bytes). **Differences in whitespace or key order alone do not change it.** Recompute it when `_load_config` rewrites `config.json`. **The server computes its `code_version` from the same `config.json` content that `_load_config` used for the configuration it runs with** (the bytes it read, or the content it wrote when it filled in keys), never by opening the file a second time; a change made after that read therefore makes the client's value differ, and the server is replaced as stale (2026-11-22, review #9: with a second read, a change between the two reads left a server running the old settings that reported the new hash, so it was never replaced and the change did not take effect).
- `pid`: PID of the server process.

#### Server check and replacement (`ensure_server`)

The CLI classifies the `/health` response as follows (`_health_decision(health)`, which returns one of `'ok'`, `'stale'`, `'foreign'`, `'legacy'`, `'none'`). Only the commands that use the server (`--buffer`, `--search`, `--repair`) and the hooks of §4 run this check; `--list`, `--recall-thread` and `--show-turn` (which read our own DB directly), `--stop` and `--init` do not:

| Response | Verdict | Action |
|---|---|---|
| Same `root`, same `code_version` | Healthy | Use it as-is |
| Same `root`, different `code_version` | Our own stale server | Stop it and restart |
| Different `root` | Another folder's server | **Do not stop it. Do not use it.** See "When the port belongs to another folder's server" below |
| No `root` (v1.3.x or older server) | Needs verification | If psutil confirms it is our own server, stop it and restart. If it cannot be verified (or cannot be stopped), treat it as another folder's server (set `_FOREIGN_SERVER_ROOT` to `(unknown: the server did not report its folder)` and emit the `port_conflict` notice) |
| No response | No server | See "PID file handling" below |

- **How to stop (`_stop_stale_server`)**: first request `POST /shutdown` (body `{"root": "<our HOME_DIR>"}`). Only for servers without `/shutdown` (such as v1.3.x), terminate the process after verifying it with psutil. **Never stop a process by the number in the PID file** (the PID may have been reused by another process).
- **Verification with psutil (`_is_own_server_process`)**: take the PID from the `pid` field of `/health`, or, if absent, from the process listening on the port (`psutil.net_connections`). Treat it as "our own server" only if its command line contains both `n3memorycore.n3memory` and `--run-server`, and the data folder resolved from its `N3MC_HOME` environment variable equals our `HOME_DIR`. If psutil is not installed, permission is denied, or anything does not match, the result is "cannot verify".
- When it cannot be verified, do not stop it; emit the notice `stale_server`: "Cannot stop the old server. Another N3MC folder may be using the same `server_port`. Check `server_port` in each folder's `config.json` and restart manually." If our own stale server (same `root`) cannot be stopped, keep using it, since it serves the same DB (`ensure_server` returns True).
- **PID file handling**: when `/health` does not respond, **only if the process with the PID-file number is verified to be this folder's server (i.e. it is starting up)**, keep the PID file and poll `/health` for up to 60 seconds (0.5 s interval). If it is still starting after 60 seconds (the first start downloads the model, which takes 2–10 minutes), **do not start another server and do not delete the PID file**: this command proceeds without the server (saves go to `_buffer_direct`, the Codex hook searches local FTS (§4), and CLI search reports that the server is still starting), and the next command checks again. This 60-second wait runs inside the hooks, so `--init` registers both hooks with `"timeout": 120` (§4 "Hook time limit"). Otherwise (the process is dead or the PID has been reused by another process), delete the PID file without waiting and start the server.
  - **The server moved to another port (2026-11-20)**: before waiting, check whether that verified process is listening on a port other than the current `server_port` (psutil, `LISTEN` connections of that PID). This happens when the user changed `server_port` while the server ran: `/health` on the new port never answers, and without this check every command would wait 60 seconds and no server would ever start. For each such port whose `/health` reports this folder's `root`, send `POST /shutdown` (body `{"root": "<own HOME_DIR>"}`) to that port, wait up to 15 seconds for the process to end, delete the PID file if it still holds that PID, and start the server on the current port without waiting. A port whose `/health` does not answer or reports another `root` is left alone. The process is still never stopped by its PID-file number. While the server is still starting it listens on no port, so the 60-second wait above applies as before.
- **psutil is required (v1.5.0)**: the PID-file check above needs psutil. Without it, v1.4.0 could never verify the starting server, deleted its PID file and started another server on every command while the model was loading (the `open(..., 'x')` guard was defeated by that deletion). If `import psutil` fails anyway (a broken install), treat every PID-file process as "still starting" for 60 seconds after the PID file's modification time and as dead afterwards; never start a second server while a PID file younger than 60 seconds exists.
- Once a server we started responds, clear the `stale_server`, `port_conflict` and `server_start_failed` notices.

#### Starting the server (`_start_server`, v1.5.0)

0. **Reserve the start before launching (2026-11-22, review #5)**: create the PID file with `open(..., "x")` before `Popen` and keep it empty until `Popen` returns, then write the child's PID into it. On `FileExistsError` another process is starting (or runs) the server: do not launch; follow "PID file handling" above. If `Popen` raises, delete the reservation. **An empty or unreadable PID file** (the moment between the reservation and the write) is treated as "still starting" for 60 seconds after the file's modification time, never as a dead process: it is not deleted and no second server is started; after 60 seconds it is treated as dead. When Windows uses a Python launcher, verify that `/health` matches the current data root and code and that the reported server process is a child of the reserved PID. Then atomically replace the reservation with the serving PID. (Until then `_start_server` called `Popen` first and created the PID file afterwards, overwriting it when it existed: two hooks starting together both launched a server — two model loads, the second one failing to bind, and a PID file that could name the process that failed.)
1. Launch `python -m n3memorycore.n3memory --run-server` with `subprocess.Popen` as in "Clean CLI" below: stdout and stdin to `DEVNULL`, **stderr appended to `.memory/server.log`** (if the file is larger than 1 MB, truncate it before starting). The server is **detached** from the hook process so that it keeps running when the hook exits: on Windows `creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW`, elsewhere `start_new_session=True`.
2. Poll `/health` every 0.5 s for up to 60 seconds. **If the child process exits while waiting (`proc.poll() is not None`), stop waiting at once** — the port is held by a program other than N3MC, a dependency is missing, the DB cannot be opened, etc. **An answer counts only when it passes the same check as `ensure_server`** (second review of 2026-11-20): `root` is this folder ("ok", or "stale" — this folder's server with other code, which the next call replaces). When another folder's server answers (two folders with the same `server_port` started at the same time, and the other one bound the port first), or a server that does not report its `root`, never use it: set `_FOREIGN_SERVER_ROOT`, emit `port_conflict` as in the table above, and go on without the server (saves go to `_buffer_direct`, and the Codex hook searches local FTS (§4)). Before this rule any answer ended the wait, and that call sent its search and save to the other folder's memory.
3. On that early exit: emit the notice `server_start_failed` ("The N3MC memory server could not start (exit code <n>). See <path of server.log> for the reason."), write the time to `.memory/server_start_failed` (a marker file), delete the PID file if it holds the PID of the child that just exited, and proceed without the server (direct save / `memory search unavailable`). If `Popen` itself raises, proceed without the server as well (one stderr line; no notice or marker).
4. While `.memory/server_start_failed` is younger than 5 minutes, do not try to start the server again; go straight to the no-server path. This keeps a broken setup from costing every hook up to 60 seconds. Delete the marker and clear the notice once a server responds.
5. If the child is still alive after 60 seconds, it is still starting (model download): leave it running and follow the "still starting" rule above.
6. The hooks are registered with `"timeout": 120` (§4 "Hook time limit") so that this wait of up to 60 seconds and the save after it end before Codex stops the hook.

> **⚠️ Why (v1.5.0, found in the Free v1.4.0 review)**: v1.4.0 waited the full 60 seconds without looking at the child process and sent its stderr to `DEVNULL`. When the port was taken by another program or the server crashed at start, every hook stalled for 60 seconds and the reason was recorded nowhere.

#### `/shutdown`

`POST /shutdown` (body `{"root": str}`). Only when `root` equals the server's own `root` does it return `{"status": "ok"}` and exit by itself after sending the response (deleting the PID file if it holds its own PID). Otherwise 403. In tests, always replace `_request_shutdown` and `_post` so nothing is sent to a real server.

#### When the port belongs to another folder's server

`ensure_server` returns False, stores that server's `root` in the module variable `_FOREIGN_SERVER_ROOT`, and emits the notice `port_conflict`. In this state, **to keep records from leaking into another folder's DB**:

- Saves (hooks, `--buffer`) are written directly to our own DB via `_buffer_direct` (embeddings are added by `/repair` once our own server runs).
- The Codex prompt hook searches its own SQLite FTS indexes (§4). CLI `--search` reports the condition as `# Recalled Memory Context\n\n_(memory search unavailable: another N3MC folder's server is using port <port>)_\n`.
- `--repair` returns without doing anything and prints the reason as one line to stderr. It does not send `/repair` either.
- `--list`, `--recall-thread`, and `--show-turn` already read our own DB directly, so they work unchanged.

#### Notices (`_notify`)

Notices that require human action (`stale_server`, `port_conflict`, `server_start_failed`, `config_unreadable`, `config_type`, `db_corrupt`, `behavior_md_edited:<hash>`) are emitted with `_notify(key, message)`:

1. Print to stderr.
2. Record `{"ts", "hook": "notice", "key", "message"}` in `audit.log` (only once for the same key and message).
3. Keep it in `.memory/notices.json` and show it at the top of the output (right after the `Search query:` line in search results, right after the `# Recalled Memory Context` heading in other outputs) **once a day** (when 24 hours have passed since it was last shown) as `> ⚠️ N3MC notice: <message>` (`_take_notices`).
4. When the cause is gone, remove it with `_clear_notice(key)`.
5. `notices.json` is written atomically (temporary file in the same folder + `os.replace`), like `config.json` (§3.5).

In tests, always point `NOTICES_FILE` and `AUDIT_LOG` to a temporary folder (never write to the real `~/.n3mc`).
- **Response Target**: Around 0.7s (total of embedding generation + DB search). Treat this as a target, not a strict requirement, as it depends on hardware, OS, and model cache state.
- **First Start**: Because model preloading runs before uvicorn starts, every start of the server takes time, not only the first one. With the model already cached, a hook that had to start the server took 41.2 seconds on the development PC (2026-11-22: the prompt hook with no server running; the next call took 0.9 seconds). When the model is not cached yet, its download takes 2–10 minutes; the hooks wait at most 60 seconds and go on without the server ("PID file handling" above). This is an accepted behavior by design; the hooks' `"timeout": 120` (§4 "Hook time limit") covers the wait.

### SQLite Durability Settings
Force the following on every connection:
```sql
PRAGMA synchronous = FULL;
PRAGMA journal_mode = WAL;
PRAGMA wal_autocheckpoint = 1000;
```

- `PRAGMA wal_autocheckpoint = 1000;` — Automatic checkpoint when WAL grows past 1000 pages (~4MB). Prevents unbounded WAL growth during long-running sessions.

### Immediate Physical Writes (No Modifications or Optimizations Allowed)
On `--buffer` or API-based saves, complete INSERT and COMMIT at that instant.

**The following are absolutely prohibited (even for performance improvement):**
- Write buffering (`write_buffer`, `batch_insert`, deferred COMMIT, etc.)
- Asynchronous writes (`asyncio`, thread queues, background tasks, etc.)
- Transaction batching (combining multiple INSERTs into one transaction)

> **Note: Background of immediate physical save**
> A record that is held in memory (buffered) instead of being committed at once is lost if the process is forcibly terminated before the deferred write. Committing at the moment of saving means a forced termination right after a save loses nothing. Durability takes priority over speed. This is not a performance choice but an immutable design constraint.

### Identifiers

- **Owner ID**: Generate a UUIDv4 on first launch and save it to `config.json`. Stamp it on every record. Used to preserve data provenance when merging N3MC instances.
- **Local ID**: Generate a UUIDv4 on first launch (if absent from `config.json`) and save it persistently. Identifier for the N3MC installation (or agent). Stamp it on every record. For multi-agent scenarios, the `/buffer` API accepts a `local_id` parameter to specify an agent-specific UUIDv4 (falls back to config.json value when omitted).
  - **Use cases**: Multiple Codex installations (each machine or install gets its own `local_id`); different agents sharing the same N3MC DB (e.g., Codex + CordX each run as separate instances with distinct `local_id`s); separating memories by agent type or project environment.
  - **Note**: In Free, `local_id` is stored per-record but not used in ranking. The `B_local` bias multiplier that prioritizes same-environment memories is a Pro feature.
- **Session ID**: A grouping key for one task / project / conversation. **Resolution order**: (1) explicit `session_id` argument on the `/buffer` and `/search` API calls (highest priority — used by hosts that already track sessions, e.g. n3memory-lite assigns task numbers, an Ollama-style chat picker can pass the chat id); (2) `N3MC_SESSION_ID` environment variable (the CLI `--buffer` / `--search` send the calling process's value as the (1) `session_id` when it is set. The resident server is usually started by a hook, so the server's own environment does not have a value the user set on the CLI side; without sending it, the user's value has no effect. 2026-11-20); (3) per-process UUIDv4 generated at server startup (fallback for clients like Codex that cannot read a host session id). Stored on every record but **not persisted to `config.json`** — `session_id` is meant to identify a transient task / project, not a persistent installation. Drives the `b_session` ranking bias (match=1.0 / mismatch=0.6) so memories from the current task surface above unrelated past sessions.

Complete `config.json` schema (auto-initialize any missing fields with the default values below):

```json
{
  "owner_id":             "<UUIDv4 auto-generated>",
  "local_id":             "<UUIDv4 auto-generated>",
  "bind_host":            "127.0.0.1",
  "server_port":          18520,
  "embed_model":          "intfloat/multilingual-e5-base",
  "half_life_days":       90,
  "bm25_min_threshold":   0.1,
  "search_result_limit":  20,
  "min_score":            0.2,
  "search_query_max_chars": 2000,
  "vector_min_cos":       0.85,
  "relative_min_score_ratio": 0.6,
  "min_results":          3,
  "pair_top_n":           3,
  "pair_max_chars":       3000,
  "version_order_enabled": true,
  "version_sim_threshold": 0.98,
  "version_min_chars":    100,
  "reply_sim_rerank_enabled": false,
  "reply_sim_alpha":      0.3,
  "reply_sim_floor":      0.80,
  "reply_sim_span":       0.15
}
```

- `bind_host`: Address the server listens on. Keep the default `127.0.0.1` (§3 "Resident FastAPI Server").
- `search_result_limit`: Maximum number of results returned by `--search` (1–1365, §3.5 "Allowed values").
- `min_score`: Excludes results whose `filter_score` (the score without `time_decay` and `b_session`; §3 "Ranking Formula") is below this value from `--search` output (default `0.2`). Set to `0.0` to disable.
- `search_query_max_chars`: Maximum characters used from a search query (default `2000`). The embedding model (512 tokens) cannot process more than ~2000 chars meaningfully. Increase at the cost of slower FTS queries.
- `vector_min_cos`: Minimum cosine similarity for a vector-search candidate (default `0.85`). With multilingual-e5, even unrelated records score 0.80–0.85, so candidates below this are discarded. **0.85 was measured with `multilingual-e5-base`.** Re-measure for other embedding models. A reasonable range is 0.80–0.88 (lower picks up more but mixes in weakly related records; higher shortens the injected context but is more likely to drop relevant records).
- `relative_min_score_ratio`: Discards results whose `filter_score` is below this fraction of the highest `filter_score` (default `0.6`; §5 "Search Result Filtering and Ordering"). Set to `0.0` to disable.
- `min_results` (v1.6.0): When fewer results than this pass the floors, the shortfall is filled with **weak matches** — candidates the floors dropped, shown under a separate heading (default `0`; §5 "Search Result Filtering and Ordering", step 7). Set to `0` to disable the fill.
- `pair_top_n` / `pair_max_chars`: Only the exchanges of the top `pair_top_n` results are injected as Q-A exchanges, up to `pair_max_chars` characters in total (§4).
- `version_order_enabled` / `version_sim_threshold` / `version_min_chars`: Ordering newer versions of the same content first (§5). `0.98` was also measured with `multilingual-e5-base`.
- `reply_sim_rerank_enabled` / `reply_sim_alpha` / `reply_sim_floor` / `reply_sim_span` (2026-11-17): Re-ranking by similarity to the reply (§5 "Search Result Filtering and Ordering", step 2b). Off by default. `0.80` and `0.15` were measured with `multilingual-e5-base`; another embedding model changes the cosine range, so re-measure them.
- `dedup_threshold` and `context_char_limit` from v1.3.x are **removed**. If they remain in an existing `config.json`, they are ignored (no need to delete them).
- Write values without quotes (`"vector_min_cos": 0.83`). Values of the wrong type or outside the allowed range are ignored (§3.5 "Allowed values").
- Editing `config.json` changes `code_version`, so the next command automatically restarts the server and the new values take effect.
- Internal processing parameters such as KNN fetch count (K value) and `--repair` batch size are left to the implementer's discretion. The K value must stay within sqlite-vec's limit of 4,096 for every allowed `search_result_limit` (the reference code uses `3 × search_result_limit`; §3.5 "Allowed values").

> **Multi-account usage on a single PC**: When running multiple Codex accounts on one machine and connecting them to the same N3MC server (same `server_port` and DB path), each account's `config.json` is auto-generated independently, resulting in different `owner_id` / `local_id` values. In the Free edition this does not affect ranking, but after upgrading to Pro, memories from other accounts will have `B_local=0.8` decay applied. To treat all accounts' memories equally, copy the first account's `config.json` to the other accounts so that `owner_id` / `local_id` are unified.

> **Team sharing: not supported.** The CLI always connects to `127.0.0.1:<server_port>` (there is no setting for a remote server address), the server has no authentication or encryption, and it rejects requests whose `Host` header is not local or that carry an `Origin` header (§3 "Resident FastAPI Server"). Keep `bind_host` at its default. Sharing one memory DB across a team would need a different design.

> **Database migration (advanced)**: The current specification assumes SQLite + sqlite-vec, but for larger teams, migration to PostgreSQL + pgvector is technically feasible. Consult Codex for schema compatibility, connection pooling, and migration procedures.

- **Primary Key**: UUIDv7 (time-sortable; generated at DB insert time). Use the external library `uuid7` (PyPI). Import it as `from uuid_extensions import uuid7` and use `str(uuid7())` as the ID (the distribution is named `uuid7` but the module is `uuid_extensions`; `import uuid7` raises `ModuleNotFoundError`).

### Ranking Formula

```
Final Score = (cos_sim × 0.7 + keyword_relevance × 0.3) × time_decay × b_session
```

**cos_sim (Mathematical Correctness)**:

$$cos\_sim = \max(0,\ 1.0 - \frac{L2\_distance^2}{2})$$

- When vectors are L2-normalized, `L2_distance² = 2(1 - cosθ)` holds, making the above formula equivalent to `cosθ`.
- Negative values (opposite-direction vectors) break ranking, so clamp with `max(0, ...)`.
- **Prerequisite**: This formula is invalid if `normalize_embeddings=True` has not been applied.

**keyword_relevance (Normalizing FTS5 BM25)**:

SQLite FTS5's `bm25()` returns negative values (more negative = more relevant). Normalize to `[0.0, 1.0]` as follows:

1. If the absolute value of the raw score is less than `bm25_min_threshold` (value from `config.json`, default `0.1`) (nearly irrelevant), set `keyword_relevance = 0.0`.
2. Otherwise, normalize by the maximum absolute value in the result set:

$$keyword\_relevance = \frac{-bm25\_score}{\max(1.0,\ \max_{results}(-bm25\_score))}$$

If the search returns 0 results, set `keyword_relevance = 0.0`.

**Exception: DBs with 2 or fewer records (2026-11-20)**: with one or two records FTS5 clamps IDF to about `1e-6`, so a genuine match scores about `-2e-6`, step 1 turns it into 0 and the keyword hit disappears (with no embedding available the search returns nothing). Only while `memories` holds 2 or fewer rows, skip step 1 and use `keyword_relevance = -bm25_score ÷ max(-bm25_score)` (the best hit is 1.0). With 3 or more records the formula above applies unchanged.

Since 2026-11-17 the keyword search runs on two FTS5 tables (trigram and CJK bigram, below). Normalize each table's bm25 by **that table's own** maximum; a record found by both keeps the higher `keyword_relevance`.

**FTS5 Table Definition**: Always create the FTS5 virtual table with `tokenize='trigram'`. **Use a standalone (non-`content=`) FTS5 table** — do NOT use the external-content variant (`content='memories', content_rowid='rowid'`). External-content FTS5 does not support the natural `DELETE FROM memories_fts WHERE rowid = ?` pattern required by `delete_memory` and the `--repair` migration loops; it requires a `INSERT INTO memories_fts(memories_fts, rowid, content) VALUES('delete', ?, ?)` ritual instead, and getting that wrong corrupts the FTS index ("database disk image is malformed"). The standalone form keeps a private FTS shadow whose rowid we align with `memories.rowid` ourselves: after `INSERT INTO memories(...)`, retrieve `cursor.lastrowid` and pass it to `INSERT INTO memories_fts(rowid, content) VALUES (?, ?)`.

```sql
-- memories table (UUIDv7 as primary key; rowid is implicitly managed by SQLite)
CREATE TABLE memories (
    id        TEXT PRIMARY KEY,  -- UUIDv7
    content   TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    owner_id  TEXT NOT NULL,
    local_id  TEXT,             -- N3MC install identifier (from config.json; can be overridden via API for multi-agent scenarios)
    agent_name  TEXT,             -- Identifies the AI agent that wrote the record (e.g. "codex"). NULL for records written before v1.1 or without agent tagging
    session_id  TEXT,             -- Conversation / task grouping key (§3 "Identifiers"); drives b_session
    turn_id     TEXT              -- Q-A exchange key shared by the [user] and [claude] rows of one turn (§4)
    -- SQLite automatically assigns an implicit INTEGER rowid to every table
);
CREATE INDEX IF NOT EXISTS idx_memories_turn_id ON memories(turn_id);

-- FTS5 standalone — rowid alignment with memories.rowid is maintained manually (trigram: substring matching that also works for Japanese)
CREATE VIRTUAL TABLE memories_fts USING fts5(
    content,
    tokenize='trigram'
);

-- CJK bigram index (2026-11-17): stores bigram_text(content); same rowid as memories
CREATE VIRTUAL TABLE memories_fts_bi USING fts5(
    content,
    tokenize='unicode61'
);

-- sqlite-vec KNN vector search (linked to memories table via rowid)
CREATE VIRTUAL TABLE memories_vec USING vec0(
    embedding float[768]
);
-- On INSERT: INSERT INTO memories_vec(rowid, embedding) VALUES (memories.rowid, serialize_vector(vec))
-- On DELETE: DELETE FROM memories_fts WHERE rowid = <rowid>; DELETE FROM memories_fts_bi WHERE rowid = <rowid>; DELETE FROM memories_vec WHERE rowid = <rowid>;
-- ⚠️ When deleting from memories, always delete from memories_fts, memories_fts_bi and memories_vec in the same transaction.
--    Orphaned records in vec/fts will corrupt search results.
```

**Schema Migration (`migrate_schema`)**: At startup, check `PRAGMA table_info(memories)` and add any missing columns idempotently:

```sql
ALTER TABLE memories ADD COLUMN local_id  TEXT;
ALTER TABLE memories ADD COLUMN agent_name  TEXT;
ALTER TABLE memories ADD COLUMN session_id  TEXT;
ALTER TABLE memories ADD COLUMN turn_id  TEXT;
CREATE INDEX IF NOT EXISTS idx_memories_turn_id ON memories(turn_id);  -- after turn_id exists
```

Additionally, `migrate_schema()` detects if the existing `memories_fts` table was created with `tokenize='porter unicode61'` and automatically recreates it with `tokenize='trigram'`, re-indexing all records. This one-time migration lets existing databases benefit from the improved Japanese search precision.

`agent_name TEXT` — identifies the AI agent that wrote the record (e.g. `"codex"`). `NULL` for records written before v1.1 or without agent tagging.

> **Note: Rationale for FTS5 Tokenizer Selection**
> `trigram` is adopted for substring matching optimized for Japanese text. Japanese has no spaces between words, so a word-boundary tokenizer such as `porter unicode61` treats a whole sentence as one token and effectively disables FTS. `trigram` indexes 3-character substrings, so Japanese keyword search works without morphological analysis. It also works for space-separated languages such as English, and the Free edition is published on PyPI and used in every country, so the default must work in any language (English word-form normalization such as "running" → "run" is not performed; the vector search covers it). Users adapt the final tokenizer to their own language and environment (e.g. `porter unicode61` for English-centric use, or a morphological analyzer); the README says so.

**FTS5 Constraint**: The `trigram` tokenizer indexes **3-character** units (characters, not bytes). A term of fewer than 3 characters — `AI`, `東京`, `龍馬` — can never match (FTS5 returns no rows for it). `_build_fts_query` therefore drops terms shorter than 3 characters; when no term is left, skip the trigram search (the bigram index below still runs). (v1.4.0 and earlier described the unit as "3 bytes", so 2-character Japanese terms such as `東京` passed the check and always returned 0 rows.)

**FTS Punctuation Stripping (mandatory on both INSERT and MATCH)**: Punctuation adjacent to words can cause tokenization mismatches. Apply the **same punctuation stripping function** both when **INSERTing into FTS5** and when **building the MATCH query**:

```python
_FTS_PUNCT_RE = re.compile(r'[「」『』【】（）()\[\]{}<>〈〉《》・、。,.!！?？;；:：\-―─…\'\"“”‘’]')

def strip_fts_punctuation(text: str) -> str:
    cleaned = _FTS_PUNCT_RE.sub('', text)
    return re.sub(r'\s+', ' ', cleaned).strip()

# On INSERT: store original text in memories table, stripped text in FTS
INSERT INTO memories_fts(rowid, content) VALUES (?, strip_fts_punctuation(content))

# On MATCH (2026-11-17): control chars and punctuation → spaces → split on
# whitespace. A word of more than 3 characters that contains CJK is split into
# its overlapping 3-character grams, and hiragana-only grams are dropped; other
# words of 3+ characters stay whole; shorter words are dropped. Remove
# duplicates, keep at most 40 terms, wrap each in "..." (escaping " as ""),
# join with OR.
_FTS_MAX_TERMS = 40  # Prevent FTS5 freeze on large text input
_FTS_CTRL_RE = re.compile(r'[\x00-\x1f\x7f]')
_CJK_CHAR_RE = re.compile(r'[぀-ヿ㐀-鿿豈-﫿가-힯]')
_HIRAGANA_ONLY_RE = re.compile(r'^[぀-ゟー]+$')

def _build_fts_query(query: str) -> str:
    terms, seen = [], set()
    for word in _FTS_PUNCT_RE.sub(' ', _FTS_CTRL_RE.sub(' ', query or '')).split():
        if len(word) > 3 and _CJK_CHAR_RE.search(word):
            grams = [word[i:i + 3] for i in range(len(word) - 2)]
            grams = [g for g in grams if not _HIRAGANA_ONLY_RE.match(g)]
        elif len(word) >= 3:
            grams = [word]
        else:
            grams = []
        for g in grams:
            if g not in seen:
                seen.add(g)
                terms.append(g)
    terms = terms[:_FTS_MAX_TERMS]
    if not terms:
        return ""                                  # → skip the trigram search
    return " OR ".join('"' + t.replace('"', '""') + '"' for t in terms)
```

- **INSERT side is unchanged** (`strip_fts_punctuation` removes punctuation and keeps words joined, as before), so no FTS re-registration or new migration marker is needed. Only the query side turns punctuation into spaces. Example: the stored `架空の惑星「アルファ9」の気温設定` is indexed as `架空の惑星アルファ9の気温設定`; the query `「アルファ9」の気温は？` becomes the terms `アルフ`, `ルファ`, `ファ9`, `の気温`, `気温は` (OR).
- **Why OR (v1.5.0, found in the Free v1.4.0 review)**: v1.4.0 joined the quoted terms with AND (FTS5's implicit operator). The hook uses the whole user message as the query, so a sentence such as `what is the quick fox doing in my DB` returned 0 rows even when a record contained `quick` and `fox`, and a Japanese sentence without spaces was one long term that matched only a record containing that exact sentence. The keyword part (30 %) of the score was therefore almost always 0 in automatic searches. With OR, a record matches when it contains any term, and FTS5's `bm25()` ranks records with more and rarer terms higher. Terms shorter than 3 characters never match under trigram and are dropped.
- **Why CJK words are split into 3-character grams (2026-11-17)**: until then a Japanese sentence without punctuation was one term and matched only a record containing that exact sentence. On a real N3MC-Pro DB (2026-11-16, 200 recent prompts), only 33% of the prompts got any FTS hit; with the grams OR-ed, 97% did, and `bm25()` ranks records by how many and how rare the shared grams are. Hiragana-only grams (`してく`, `ください`) appear in most records and are dropped. This also turns a space-separated query (English) into OR of its words, as before.

**CJK bigram index (`memories_fts_bi`, 2026-11-17)**: the trigram index cannot match a 2-character word (`記憶`, `設定`, `PR`). A second standalone FTS5 table (`tokenize='unicode61'`) stores `bigram_text(content)`: after `strip_fts_punctuation`, each CJK run becomes its overlapping 2-character grams and other runs stay whole (`N3MCの設定` → `N3MC の設 設定`).

- `insert_memory` writes both tables. **Every delete path** deletes from both (see above).
- The query side (`build_bigram_query`) OR-s the query's bigram tokens, quoted. Hiragana-only tokens are dropped when anything else is left; a 1-character non-CJK token is dropped.
- `hybrid_search` always searches both tables (`search_fts` and `search_fts_bigram`) and merges them as described under "keyword_relevance". If the bigram search fails, continue with the trigram results.
- Records saved before the table existed are indexed once by `--repair` (key `fts_bigram` of the `meta` table, §3.5; not limited by `max_records`, since it embeds nothing).
- Why (measured in N3MC-Pro, 2026-11-16, 138 labeled questions): removing the bigram index lowered MRR by 0.046 (95% interval −0.089 to −0.007).

> **⚠️ Quoting each term is mandatory (v1.4.0)**: Even after punctuation stripping, ASCII symbols such as `\ / # = @ * $ % + ^ ~ |` and bare `AND` / `OR` / `NOT` / `NEAR` remain. Passing them to `MATCH` as-is causes an FTS5 syntax error (`fts5: syntax error near "\"`, etc.), `/search` returns HTTP 500, and memory injection degrades to "memory search unavailable" (observed on about 12% of prompts). Wrapping each term as an FTS5 string `"..."` makes symbols and operators match literally. (Since v1.5.0 the quoted terms are joined with `OR`; the `OR` written between them is outside the quotes and is the operator, while a user's `OR` inside a term stays literal.)
>
> **Keep searching on exceptions**: `hybrid_search` catches exceptions from `search_fts` and continues with no keyword results (vector search only). An FTS failure must not fail the whole search.

During `--repair`, detect existing FTS records that were indexed with punctuation and re-register them with stripped text. This FTS cleaning runs as a **one-time migration**: after completion, write the key `fts_punct_cleaned` of the `meta` table (§3.5 "Index metadata"). If the key exists, skip the scan to avoid a full-table scan on every session start.

**Score for FTS-only Hits**: Records that appear in FTS results but not in vector search results should be included in results with `cos_sim = 0.0` for integrated score calculation. Their final score is at most `0.3 × time_decay × b_session`, but they must not be excluded from ranking. Because `min_score` (0.2) and the relative cutoff are judged on `filter_score` (the score **without** `time_decay` and `b_session`, below), a keyword-only hit (at most 0.3 as a `filter_score`) is kept when its `keyword_relevance` is at least 0.67, however old it is and whichever session wrote it.

**Vector Search owner_id Filter**: Since `search_vector` is a single-user system, no filtering by `owner_id` is performed. KNN search targets all records. (This is a deliberate design decision; multi-user support would require rework.)

**Filtered vector search (`--since` / `--until`)**: vec0 KNN (`k = ?`) first selects the k nearest records from the whole table, so applying the time range afterwards leaves almost no in-range records. When a filter is present, **run KNN only over the filtered rowids**. Do it in two steps:

```sql
-- 1) get rowid and distance from memories_vec
SELECT rowid, distance FROM memories_vec
 WHERE embedding MATCH :vec AND k = :k
   AND rowid IN (SELECT rowid FROM memories WHERE timestamp >= :since AND timestamp <= :until)
-- 2) look up memories by those rowids
```

- KNN with `rowid IN (subquery)` is confirmed on sqlite-vec v0.1.7. If it raises `sqlite3.OperationalError` (older sqlite-vec, etc.), fall back to computing `vec_distance_l2(embedding, :vec)` for every filtered row and sorting by distance (`_search_vector_exact`).
- Without a filter, use `search_vector` (KNN over the whole table) as before.

**time_decay (half-life of `half_life_days` days)**:

$$time\_decay = 2^{-\frac{days\_elapsed}{half\_life\_days}}$$

`days_elapsed` is the elapsed days (floating point) since the record's creation timestamp. Use the `half_life_days` value from `config.json` (default 90).

`time_decay` **only orders** the results (v1.6.0): it is part of `score`, not of `filter_score`, so an old record is ranked below a newer one of the same relevance but is never dropped for its age (see the table below).

**Bias coefficients (Free edition)**:

| Bias | Condition | Coefficient (fixed value) |
| :--- | :--- | :---: |
| **$b_{session}$** | Matches current `session_id` | **1.0** |
| | Mismatch or NULL | **0.6** |

- `b_session` is the **only** bias multiplier in Free. It groups memories that belong to the same task / project / conversation, so the ongoing exchange surfaces above unrelated past sessions. The stronger `0.6` mismatch penalty makes the current session the primary ranking signal beyond raw similarity and freshness.
- Bias coefficients are fixed values and cannot be changed via the configuration file.
- Compute `b_session` in Python, in the same loop that merges the vector and FTS candidates (the two result sets are combined in Python, so a SQL `CASE` would not help).

**`time_decay` and `b_session` order; they do not filter (`b_session` since v1.5.0, `time_decay` since v1.6.0)**: every candidate carries two values:

| Value | Formula | Used for |
|---|---|---|
| `score` | `filter_score × time_decay × b_session` = `(cos_sim × 0.7 + keyword_relevance × 0.3) × time_decay × b_session` | The order of the results (and the `score=` shown) |
| `filter_score` | `cos_sim × 0.7 + keyword_relevance × 0.3` (no `time_decay`, no `b_session`) | `min_score` and the relative cutoff (§5 "Search Result Filtering and Ordering", steps 2 and 4), and the order of the weak matches (step 7) |

> **⚠️ Why (v1.5.0, found in the Free v1.4.0 review)**: in v1.4.0 both floors compared the final score, so `b_session` (0.6) and the relative cutoff (0.6) multiplied. As soon as the current session had one vector hit (cos ≥ 0.85, score ≥ 0.6), another session's record needed `cos × time_decay ≥` the top cos to survive: with the 90-day half-life, **every record from another session older than about 21 days was cut even when its content matched exactly** (reproduced: a current-session record at cos 0.86 stayed, a 30-day-old record from another session at cos 0.99 scored 0.33 and fell under the cutoff 0.602 × 0.6 = 0.361). A keyword-only hit from another session (at most 0.18) was always under `min_score` 0.2, and manual `--search` treats every record as another session, so it never showed keyword-only hits. The current session's records are already in Codex's context; cutting everything else defeated the purpose of cross-session memory.

> **⚠️ Why `time_decay` left `filter_score` too (v1.6.0, found when scoring v1.5.0)**: v1.5.0 still multiplied `filter_score` by `time_decay` and compared it with `min_score` (0.2). With the 90-day half-life, a record stopped being returned at about 150 days (cos 0.86) to 180 days (cos 0.95) **even when it was the only record in the DB**; it stayed in the DB and in `--list`, but search could no longer reach it. In a measurement with the real model (50 records, 26 questions), making every record one year older dropped recall@3 from 23/26 to **0/26**. §1 promises a lifelong asset, so age may lower a record's rank but must not hide it. Without `time_decay` in `filter_score`, the one-year-old set returned 23/26 again, with the same number of results and no more noise.

- `b_local` (agent / installation grouping) is **not** applied in Free — every record is treated as `b_local = 1.0` regardless of match. The `B_local` multiplier that separates memories per agent / install is a **Pro feature**; in Pro it applies `b_local = 1.0` on match and `b_local = 0.8` on mismatch.

### Clean CLI
Keep model load warnings and similar output out of the CLI's stdout (which becomes Codex's context). When launching the FastAPI server as a subprocess from `n3memory.py`, redirect its streams as follows (handled internally, not by the caller):

```python
import os, subprocess, sys
log = open(SERVER_LOG, "ab")          # .memory/server.log, truncated first if > 1 MB
kwargs = {}
if os.name == "nt":
    kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
else:
    kwargs["start_new_session"] = True
proc = subprocess.Popen(
    [*python_cmd(), '-m', 'n3memorycore.n3memory', '--run-server'],   # python_cmd(): "Safe import path" below
    stderr=log, stdout=subprocess.DEVNULL, stdin=subprocess.DEVNULL, **kwargs,
)
```

- stderr goes to `.memory/server.log`, not `DEVNULL` (v1.5.0), so a server that fails to start leaves its reason behind (§3 "Starting the server").
- The detach flags keep the server alive after the hook process that started it exits.

- The `-m n3memorycore.n3memory` form is required so the package's relative imports resolve. Do **not** spawn the server by absolute file path.
- The caller (e.g., hooks in `hooks.json`) does not need to add any redirects.

**Safe import path (2026-11-21)**: `python -m <module>` puts the current folder first on `sys.path`. The hooks and the commands of §4 run in the folder the user has open in Codex. Without the two rules below, a file in that folder with the name of any module N3MC imports (for example `shlex.py` or `fastapi.py` in a repository the user has just cloned) is imported, and runs, inside N3MC.

**Rule 1 — entry modules drop the current folder.** Every module of the package that can be the program's entry — the ones started with `python -m`; here `n3memory.py` — has the following block as its **first statements**, right after the docstring and before any other import. The hook entry `codex_entry.py` does not have it: its registered command starts Python with `-I` (§4), which keeps the current folder off `sys.path`:

```python
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
```

- It acts only when the module is the program (`python -m …`). Imported by a console script or by a test, it does nothing: a library must not change the `sys.path` of the program that imports it.
- `os` and `sys` are already loaded when the block runs, so importing them reads no file.
- The entry is kept when the package itself lives in the current folder (a source checkout run in place, not installed): without it the package could not be found.

**Rule 2 — children are started with `python_cmd()`.** `paths.py` has:

```python
def python_cmd():
    """The command that starts a child Python: [sys.executable], plus -P on Python 3.11 and later so
    that the child does not put the current folder on sys.path (see the safe-path block at the top of
    the entry modules). -P is left out when this package itself lives in the current folder (a source
    checkout run in place), because the child could then not find the package."""
    import sys
    cmd = [sys.executable]
    try:
        cwd = os.path.normcase(os.path.abspath(os.getcwd()))
        pkg_parent = os.path.normcase(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        if sys.version_info >= (3, 11) and pkg_parent != cwd:
            cmd.append("-P")
    except Exception:  # noqa: BLE001
        pass
    return cmd
```

Every child Python process — the server in the code above — is started as `[*python_cmd(), '-m', …]`, never as `[sys.executable, '-m', …]`. `-P` (Python 3.11) keeps Python from adding the current folder at all, which also covers a folder there that has the name of this package.

**What the rules do not cover**: a folder or file in the current folder with the name of this package itself (`n3memorycore`), when the program is entered by `python -m …` typed in that folder (the commands of §4, and a hook registered in the `python -m` form). The block is never reached, because the other package is the one that is imported. On Python 3.10 the same holds for the children (there is no `-P`), and a `runpy.py` in that folder runs as well. Entering through the console scripts, or with `python -P -m …` on Python 3.11 and later, avoids it. (Checked 2026-11-21: with `shlex.py` in the current folder, `python -m n3memorycore.n3memory` ran that file before these rules and does not run it with them; a folder `n3memorycore/` there still runs.)

**Character Encoding (UTF-8)**: At the start of `main()` in `n3memorycore/n3memory.py`, **AND in `n3memorycore/codex_entry.py` before stdin is read**, execute the following to resolve character corruption in Windows cp932 environments from within the program itself:

```python
for _stream_name in ("stdin", "stdout", "stderr"):
    _s = getattr(sys, _stream_name, None)
    if _s is not None and hasattr(_s, 'reconfigure'):
        try:
            _s.reconfigure(encoding='utf-8')
        except Exception:
            pass
```

- With this, the caller does not need to specify `python -X utf8`.
- `reconfigure` is available from Python 3.7 onward. For older environments, use the `PYTHONUTF8=1` environment variable as an alternative.
- All multilingual text (Japanese, English, Chinese, etc.) is unified as UTF-8.
- ⚠️ **The reconfigure block is required in EVERY Python entry point that reads stdin or pipes stdin into a subprocess** — that includes `n3memorycore/n3memory.py` AND `n3memorycore/codex_entry.py`. Forgetting it on either of them silently mojibakes non-ASCII input on Windows (Japanese, em-dashes, etc.); the corrupted bytes are then persisted to `audit.log` and the DB and cannot be recovered. In the hook entry, run the block before stdin is read for the first time.

**Path Portability**: All file path construction in Python code must use `os.path.join()` or `pathlib.Path`. Hardcoded path separator characters (`\` or `/` as string literals in path construction) are prohibited. The system must run on Windows and Linux without code changes.

```python
# Correct
import os
db_path = os.path.join(base_dir, "data", "memory.db")

# Also correct
from pathlib import Path
db_path = Path(base_dir) / "data" / "memory.db"

# Prohibited — hardcoded separator
db_path = base_dir + "/data/memory.db"   # NG
db_path = base_dir + "\\data\\memory.db" # NG
```


- Supported platforms are **Windows and Linux** (tested on Windows 11 and Ubuntu). macOS is not a target (v1.5.0; earlier versions listed it). Regenerating from this spec on either OS must produce a working implementation without code changes.

---

## 3.5. Resilience & Error Handling

### config.json Corruption Recovery

Users edit `config.json` by hand (e.g. to tune `vector_min_cos`), so assume it may contain mistakes. **Never overwrite a mistyped `config.json`** (the earlier implementation overwrote an unreadable file with defaults, wiping user settings such as a changed port).

| Case | Behavior |
|---|---|
| File does not exist | Save the defaults with a new `owner_id` and `local_id`, **creating the file exclusively** (see "Writing config.json" below) |
| Not valid JSON, or the top level is not an object | **Do not rewrite `config.json`.** Run on the defaults meanwhile. Recover `owner_id` / `local_id` from the DB (below); if the DB has none either, use a new UUID **for this run only** (not saved). Emit the notice `config_unreadable` |
| A value's type differs from the default (e.g. `"vector_min_cos": "0.83"` — a quoted number), or the value is outside its allowed range (table below) | Ignore **only that key** and use its default; use the other keys. Do not rewrite `config.json`. Emit the notice `config_type` naming the key |
| Reads correctly | Add any missing IDs or default keys and save. Clear the `config_unreadable` and `config_type` notices |

- Type check (`_config_value_ok(key, value)`): if the default is a boolean, accept only booleans; if a string, accept only strings; numbers follow the table below (booleans are never numbers). Keys whose default is `None` (`owner_id`, `local_id`) and keys not in the defaults are not checked.

**Allowed values (v1.5.0)**:

| Keys | Type | Allowed range |
|---|---|---|
| `server_port` | integer | 1–65535 |
| `search_result_limit` | integer | 1–1365 |
| `pair_top_n`, `pair_max_chars`, `search_query_max_chars`, `version_min_chars` | integer | ≥ 1 |
| `min_results` (v1.6.0) | integer | ≥ 0 |
| `half_life_days` | number (int or float) | > 0 |
| `bm25_min_threshold` | number | ≥ 0 |
| `min_score`, `vector_min_cos`, `relative_min_score_ratio`, `version_sim_threshold`, `reply_sim_alpha`, `reply_sim_floor` | number | 0–1 |
| `reply_sim_span` | number | > 0 |

- "Integer" means a JSON integer (`2000`). A float such as `2000.0` is **not** accepted, even when its value is whole: these keys are used as slice bounds and counts (`user_text[:search_query_max_chars]`), and v1.4.0 accepted `2000.0`, after which every prompt hook call failed with `TypeError` before searching and the user message never reached the DB (it was only in `audit.log`). A negative `server_port` or `half_life_days: 0` also passed v1.4.0's check.
- Out-of-range values are treated exactly like wrongly typed ones: that key alone uses its default and the `config_type` notice names it.
- **Why `search_result_limit` stops at 1365 (final review of 2026-11-18, C-06)**: the reference code's vector search asks sqlite-vec for `k = 3 × search_result_limit` neighbours, and sqlite-vec refuses a `k` above 4,096. With 1366 or more, every vector search returned nothing (sqlite-vec: "k value in knn query too large"; only a log warning) and the search went on with keyword hits only. 3 × 1365 = 4,095 is the largest value that works.

**Writing `config.json` (v1.5.0)**:

- **Creating** a missing file uses exclusive creation (`open(path, "x")`). If it fails with `FileExistsError`, another process created the file first: read that file instead of writing. Two hooks starting at the same time on a fresh install therefore end up with one `owner_id` (v1.4.0 could write two different ones, the second overwriting the first after records had been stamped with it).
- **Updating** an existing file (adding missing keys) writes a temporary file in the same folder and replaces the original with `os.replace`, so an interrupted write never leaves a truncated `config.json`. `notices.json` is written the same way.
- **Filling in `owner_id` / `local_id` of an existing file (2026-11-22, review #2)** is serialized across processes: take the lock file `.memory/config.lock` with exclusive creation (retry every 0.05 s for up to 10 s; a lock file older than 10 s is stale and is removed), read `config.json` again inside the lock, add only what is still missing, write it with `os.replace`, then delete the lock. Every process uses the IDs found on disk (or written) under the lock. When the lock cannot be taken within 10 s (or cannot be created at all), fill in without it, as before. (Until then two processes that read the same file without IDs, with no records in the DB to recover them from, each wrote its own `owner_id`, and the records of the process that lost carried an ID that is not in the file.)
- Notices go through the §3 "Notices" mechanism (stderr, `audit.log`, and once a day at the top of search results). Fixing the file clears them on the next load.
- **ID recovery from the DB**: if `owner_id` or `local_id` cannot be obtained, use the most frequent value from existing DB records (`SELECT owner_id FROM memories GROUP BY owner_id ORDER BY COUNT(*) DESC LIMIT 1`). Only generate a new UUID if the DB also has no records.

> **Note: Background of DB-based ID recovery**
> If `owner_id`/`local_id` are silently regenerated, bias calculations for all existing memories become incorrect. DB recovery prevents this silent failure.

### DB Corruption Detection and Recovery

At server startup (`lifespan`), run the full `PRAGMA integrity_check` exactly once. In the `_buffer_direct` fallback path, run **`PRAGMA quick_check`** instead — `integrity_check` walks every row of every table and takes seconds-to-minutes on large DBs, which is unacceptable for a fallback path triggered on every HTTP failure, so the lightweight `quick_check` is used there. **Run the `quick_check` at most once per process** (v1.5.0): remember the result in a module variable. While another folder's server holds the port, every chunk goes through `_buffer_direct`, and v1.4.0 ran `quick_check` once per chunk. In either case:

1. If the result is not `ok`, set the DB aside as `n3memory.db.corrupt-<YYYYmmddHHMMSS>.bak` (local time; if that name exists, `…-2.bak`, `…-3.bak`, …).
2. **Move** the `n3memory.db-wal` and `n3memory.db-shm` sidecar files with it, under the same name pattern (`n3memory.db.corrupt-<YYYYmmddHHMMSS>.bak-wal`, `…-shm`), instead of deleting them. The new empty DB must not replay the old WAL — moving them away achieves that just as deleting did — and the WAL may hold the most recent records, which `sqlite3 <backup> ".recover"` can still read when it sits next to the backup under matching names (rename them back to `<name>-wal` / `<name>-shm` before recovering).
3. Create a new empty DB.
4. Output a warning message to stderr (including recovery instructions), and emit the notice `db_corrupt` ("The memory DB failed its integrity check and was set aside as <path>. A new empty DB is in use. To recover records: sqlite3 <path> .recover | sqlite3 recovered.db"). The notice appears at the top of search results like every notice (§3 "Notices").

> **⚠️ Why (v1.5.0, found in the Free v1.4.0 review)**: v1.4.0 used the fixed name `.corrupt.bak`, so a second corruption overwrote the first backup (confirmed on Windows), and it deleted the WAL and SHM files, discarding records that a recovery could have used. The only signal was a stderr line that hooks never show.

**A damaged file that makes SQLite raise (final review of 2026-11-18, F13)**: when opening the DB (the `PRAGMA`s inside `get_connection`) or the check itself raises `sqlite3.DatabaseError` — not its subclass `OperationalError` (e.g. `database is locked`) — whose message contains `file is not a database` or `malformed` (`database disk image is malformed`), treat it like a result other than `ok`: steps 1–4 above (set aside, new empty DB, notice). One helper does this for both checks: `_connect_checked(pragma)` opens `DB_PATH`, runs `PRAGMA <pragma>` (`integrity_check` at startup, `quick_check` once per process in `_buffer_direct`, none after that) and returns an open connection; `_is_corruption_error(e)` is the test above. `get_connection` closes its connection before re-raising a failed `PRAGMA`, so the file can be moved on Windows. Any other `DatabaseError` is raised unchanged; the failure to load sqlite-vec keeps its own message with `Recovery: pip install sqlite-vec`. (Until then only a check that returned rows other than `ok` was handled: a file of garbage gave `file is not a database`, a damaged first page `database disk image is malformed`, nothing was set aside and no notice was given, every save of the hooks failed with "Physical save failed" on stderr only, and the server did not start.)

### Migration Batch Processing

Bulk migrations inside `/repair` (vector re-indexing, FTS punctuation cleaning) execute in **batches of 200**. To prevent OOM on large DBs, fetch using `LIMIT 200` instead of `fetchall()`. **Always keep `OFFSET` at `0`** — repaired records automatically drop out of the `WHERE mv.rowid IS NULL OR mf.rowid IS NULL` result set, so incrementing `OFFSET` across batches would skip the remaining unrepaired records (e.g., 400 unrepaired → 200 repaired → `OFFSET 200` returns 0 rows → remaining 200 permanently skipped). Exit immediately if a batch produces zero progress (e.g., embedding model unavailable) to prevent infinite loops.

**No write lock while embedding (final review of 2026-11-18, F11)**: the vector repair computes the embeddings of the whole batch first, outside any transaction (an open one is committed before), and only then inserts the batch's `memories_vec` / `memories_fts` / `memories_fts_bi` rows and commits — the same order as `--reembed`. (Until then the first `INSERT … memories_vec` opened the write transaction, which stayed open while the rest of the batch — up to 200 records — was embedded; a `/buffer` that arrived meanwhile waited for the busy timeout and failed with `database is locked`, and so did its `_buffer_direct` fallback, so the prompt was not saved. Reproduced with 60 records and a stand-in model of 0.25 s per record.) **Check again before writing (2026-11-20)**: after the embeddings, take the write lock with `BEGIN IMMEDIATE`, and for each row of the batch check that the `memories` row still exists and is the same record (same `id` or `content`) and that `memories_fts` / `memories_fts_bi` / `memories_vec` still have no row for that rowid; write only what is missing. Rows another call (a hook in another window, a manual `--repair`) has filled meanwhile, and rows deleted meanwhile, are skipped. (Before, when two calls read the same unrepaired row, the later one stopped with `UNIQUE constraint failed on memories_vec primary key` (2026-11-20, reproduced in the review of N3MC Pro's generated code).)

**Per-call limit for hooks (v1.5.0)**: `/repair` accepts an optional body `{"max_records": int}`. The prompt hook sends `{"max_records": 200}` (one batch), so a large backlog — e.g. many records saved through `_buffer_direct` while another folder's server held the port — is worked off a batch per turn instead of blocking one prompt for minutes. `n3mc --repair` sends no limit and processes everything. The one-time migrations (FTS punctuation cleaning, vector re-index) follow the same limit; their markers are written only when the migration has finished.

The **FTS punctuation cleaning** is the exception: processed rows do not drop out of its result set (they are only UPDATEd), so `OFFSET 0` would never finish. Page it with a keyset instead: `WHERE rowid > <last rowid of the previous batch> ORDER BY rowid LIMIT 200`. **Carry on where the last call stopped (2026-11-20)**: write the last rowid done to the `meta` key `fts_punct_cursor` in the same transaction as each batch's rewrites; the next call starts after it, not at rowid 0 (so calls with `max_records` keep moving on, also across restarts). When the last row has been read, write `fts_punct_cleaned` and delete `fts_punct_cursor`. (Before, every call with a limit started again at rowid 0, never reached row 201, and never wrote the marker (2026-11-20, reproduced in the review of N3MC Pro's generated code).)

### Index metadata (`meta` table) and `--reembed` (v1.8.0)

The facts that describe how the indexes of `n3memory.db` were built live **inside the database**, in a table created by `init_db`:

```sql
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
```

| Key | Value | Written by |
|---|---|---|
| `embed_model` | name of the model that made the vectors in `memories_vec` | `/repair` (first time) and `--reembed` |
| `embed_dim` | dimension of `memories_vec`, read from the table itself (`768` for a table created by `init_db`) | same |
| `embed_model_at` | when `embed_model` was written (UTC ISO 8601) | same |
| `fts_punct_cleaned` | `1` when the FTS punctuation cleaning has finished | `/repair` |
| `fts_punct_cursor` | The last rowid the FTS punctuation cleaning has done; deleted when it finishes (2026-11-20) | `/repair` |
| `fts_bigram` | `1` when `memories_fts_bi` has been filled for older rows | `/repair` |
| `reembed_model`, `reembed_cursor` | progress of an unfinished `--reembed` | `--reembed` (removed when it finishes) |

- **`/repair`** runs a one-time step (FTS punctuation cleaning, bigram fill) when its key is missing **in the database**, and writes the key only when the step has finished. Both steps are idempotent, so running one again on a database that had it already only costs one scan.
- **Dimension of `memories_vec` (2026-11-22, review #3)**: always read from the table itself — the number in `float[N]` of `SELECT sql FROM sqlite_master WHERE name = 'memories_vec'` — never from the constant `EMBED_DIM`. `/repair` writes that value to `embed_dim` when it fills in missing `meta` rows, and `--reembed` (step 2 below) compares the probe vector with it. (Until then both used 768: after the manual procedure of §3 "Embeddings" with a 384-dimensional table, `--reembed` said `memories_vec has 768` and exited with status 1, so the vector index could not be rebuilt.)
- **`embed_model` when missing**: if `memories_vec` has no rows, the configured `embed_model`; otherwise the content of `.memory/vec_model.txt` when that file exists and is not empty (the marker of v1.7.0 and earlier); otherwise the configured `embed_model`. The file is only read for this; it is never written or deleted.
- **Model mismatch**: when `meta.embed_model` differs from the configured `embed_model`, `/repair` emits the notice `embed_model_mismatch` (§3 "Notices"): `The stored vectors were made with <recorded>, but config.json sets embed_model to <configured>. Search quality is degraded until they are re-made: run n3mc --reembed (it re-embeds all <N> records with <configured>), or set embed_model back to <recorded>.` When they match, the notice is cleared.
- **`n3mc --reembed`** re-embeds every record with the configured `embed_model`, **in the CLI process** (it can take minutes; an HTTP call would time out):
  1. Stop this folder's server (the same `/shutdown` request as a stale server, §3 "Starting the server"), so that it is started again with the configured model by the next CLI call. A server of another folder is left alone.
  2. Load the configured model and embed one probe text. If its dimension differs from the dimension of `memories_vec` (read from the table, above), print `N3MC: --reembed: <model> makes <d>-dimensional vectors but memories_vec has <D>; a different dimension needs the manual procedure in §3 "Embeddings".`, change nothing, and exit with status 1.
  3. Resume point: when `meta.reembed_model` equals the configured model, start after `meta.reembed_cursor` (a `memories.rowid`); otherwise start from the beginning and write `reembed_model`.
  4. Batches of 200 rows ordered by `rowid`: embed the batch (`"passage: " + content`, normalized), then in one transaction delete those rows from `memories_vec`, insert the new vectors, and set `reembed_cursor` to the last rowid. Print `Re-embedded <done> / <total>` to stderr after each batch.
  5. When no rows remain: set `embed_model`, `embed_dim`, `embed_model_at`; delete `reembed_model` and `reembed_cursor`; clear the `embed_model_mismatch` notice; print `Re-embedded <N> record(s) with <model>.`
  - An interrupted run (Ctrl+C, crash) keeps every finished batch; running `--reembed` again continues from the cursor. Rows saved while it runs are embedded by the restarted server with the configured model.
  - `--reembed` is an operator maintenance command.

> **Why (v1.8.0, design review of 2026-11-17, proposal 3)**: up to v1.7.0 these facts were marker files next to the database (`vec_model.txt`, `fts_punct_cleaned`, `fts_bigram_v1`), but the backup procedure saves `n3memory.db` and `config.json` only. Restoring an older backup on the same PC kept the newer markers, so the bigram fill was skipped and older records lost their CJK keyword hits; moving a database built with another model to a new PC wrote the configured model into a new `vec_model.txt`, so the mismatch was never reported. The warning also said "delete `vec_model.txt`, then run `n3mc --repair`", but `--repair` only adds vectors that are missing: the old vectors stayed and the warning went silent.

---

## 3.6. Retrieval Extensions

> **Purpose**: Strengthen retrieval over already-saved memories. All entries here are **additive**; existing schemas, existing CLI flags, and existing behaviors are not modified.

### `--since` / `--until` (Time-Range Filter)

```bash
python -m n3memorycore.n3memory --search "keyword" --since 2026-01-01 --until 2026-03-31
```

- Accepted as options on `--search` and `--list`.
- AND-combines `WHERE timestamp >= ? AND timestamp <= ?` against the existing `timestamp` column. No schema additions.
- **Parsing (`_parse_time_bound`, v1.5.0)**: accept a date (`2026-11-13`) or an ISO 8601 datetime with `T` or a space between date and time (`2026-11-13T09:00`, `2026-11-13 09:00:00`), with or without an offset (`+09:00`, `Z`). A date-only `since` means 00:00:00 and a date-only `until` means 23:59:59.999999.
- **Time zone**: a value without an offset (including every date-only value) is read in the **local time zone** of the machine — the same clock as `saved=` in the output — and converted to UTC. A value with an offset is converted to UTC as given. The converted bound is formatted exactly like the stored `timestamp` values (the format `insert_memory` writes, UTC) so the string comparison in SQL is correct.
- **Format of the stored `timestamp` (2026-11-19, written down from the code)**: every record is saved with `datetime.now(timezone.utc).isoformat()` — for example `2026-11-13T01:34:56.123456+00:00` (microseconds, offset `+00:00`, never `Z`). The bounds of `--since` / `--until` are produced with `dt.astimezone(timezone.utc).isoformat()`. SQL compares these values as strings, so another format (a `Z` suffix, no microseconds) would compare wrongly against the rows of an existing DB. A stored value without an offset is read as UTC by `time_decay`; a value that cannot be parsed gives `time_decay` = 1.0.
- **Unreadable values**: if a bound cannot be parsed (`yesterday`, `2026-13-01`), print one line to stderr (`--since: cannot read 'yesterday' (use 2026-11-13 or 2026-11-13T09:00)`) and exit with status 2 without searching. If `since` is later than `until`, do the same with `--since is later than --until`.
- Either bound may be specified alone (open-ended range).

> **⚠️ Why (v1.5.0, found in the Free v1.4.0 review)**: v1.4.0 compared the raw argument string with the UTC timestamps in the DB. In Japan, `--since 2026-11-13` dropped records saved between 00:00 and 08:59 local time on the 13th (they are on the 12th in UTC) even though `saved=` showed them as the 13th; `yesterday` was compared as a string without any error; and `2026-01-01 10:00:00` (space) sorted wrongly against the `T`-separated stored values.

### `--recall-thread` (Conversation Reconstruction)

```bash
python -m n3memorycore.n3memory --recall-thread <turn_id> [--before N] [--after N]
```

- Returns the target `turn_id` plus the N preceding and N following turns, in chronological order.
- Defaults: `--before 2`, `--after 2`.
- Uses the existing `idx_memories_turn_id` index. No new index required.
- Default TSV matches `--list` and ends with `Total: N records`. `--format jsonl` emits JSON records only.
- **Which rows (2026-11-19, written down from the code)**: take the smallest and the largest `rowid` of the target turn. The N preceding turns are the N distinct `turn_id`s (not NULL, not the target) with the largest `MAX(rowid)` below the target's smallest rowid; the N following turns are those with the smallest `MIN(rowid)` above the target's largest rowid. Rows whose `turn_id` is NULL are never counted as a turn. Print every row of the selected turns in `rowid` order. When there is no DB file, print `No DB found at <path>` to stderr. Neighbors must share the target session and be entirely before or after it.
- **`--format jsonl` keys**. `--list` prints `id, content, timestamp, owner_id, local_id, agent_name, session_id, turn_id, role, source, state, replacement_turn_id`. `--recall-thread` prints `id, timestamp, agent_name, turn_id, content`.
- **Operational rule**: When the snippet returned by `--search` is insufficient, Codex should pass the hit's `turn_id` to `--recall-thread` to retrieve surrounding context. End users do not need to invoke this command directly.

---

## 3.7. Backward Compatibility (Mandatory)

No feature added by this specification may break the existing `memories` / `memories_vec` / `memories_fts` schemas or the behavior of existing CLI flags. New features MUST be implemented as one of the following:

- New CLI flags or new subcommands
- New DB tables or new indexes (`CREATE TABLE IF NOT EXISTS` / `CREATE INDEX IF NOT EXISTS`)
- Column additions to existing tables only via `ALTER TABLE ... ADD COLUMN` (`DROP` / `RENAME` are forbidden)

Existing user DBs MUST continue to operate under the new specification without regeneration.

---

## 3.8. CLI inputs and outputs

Use the installed `n3mc` command or `python -I -m n3memorycore.n3memory` with the Python environment where it is installed. For normal conversation capture, use the hooks in §4.

| Command | Input, output and behavior |
|---|---|
| `--help` | No arguments. Prints usage to stdout. |
| `--init` | Prints the data path, config and hook registration outcome. Invalid hook configuration is preserved and exit status is 1. |
| `--buffer [TEXT]` | Saves the text. Omitting the argument or using `-` reads UTF-8 stdin. Supports `--agent-id NAME` and `N3MC_SESSION_ID`. Normal success has empty stdout. |
| `--search QUERY` | Supports `--since` / `--until`. Uses `N3MC_SESSION_ID` for session ranking and prints Markdown to stdout. |
| `--repair` | Repairs search indexes and reports changed records to stderr. Unavailability or failure returns status 1. |
| `--reembed` | Rebuilds vectors using the configured model. Progress and result go to stderr. Failure returns status 1. A rerun resumes after committed batches. |
| `--list` | Supports `--since` / `--until`. Default output is four TSV columns and a total. `--format jsonl` emits one record per line. |
| `--recall-thread TURN_ID` | Returns surrounding turns in the same conversation. `--before` and `--after` each default to 2. Supports TSV and JSONL. |
| `--show-turn TURN_ID` | Prints the complete turn and local timestamps to stdout. |
| `--stop` | Cleans up expired markers and rotates the audit log. Server shutdown uses `POST /shutdown` in §3. |
| `--run-server` | Runs the server in the foreground using `config.json`. Defaults to `127.0.0.1:18520`. |
| `--backup NEW_DIRECTORY` | Creates an online SQLite snapshot, config and checksummed manifest in a new directory. Returns JSON with `path` and `records`. |
| `--restore-backup DIRECTORY --to-home NEW_DIRECTORY` | Verifies the backup hashes and DB, then restores to a new data home. Returns JSON with `path` and `records`. |
| `--export-records NEW_FILE` | Writes text, provenance, lifecycle and index metadata as JSONL to a new file. Returns JSON with `path`. |
| `--forget-turn TURN_ID [--yes]` | Previews by default. `--yes` deletes the turn’s text and index entries and prevents a retry from saving it. Returns JSON. |
| `--supersede-turn OLD --replacement-turn NEW [--yes]` | Previews by default. `--yes` excludes the old turn from ordinary search and preserves its history. Returns JSON. |

Backup and lifecycle commands print errors to stderr and exit with status 1. Usage errors return status 2.

---

## 4. Codex hooks

- `--init` merges synchronous `UserPromptSubmit` and `Stop` command handlers into `$CODEX_HOME/hooks.json` (default `~/.codex/hooks.json`). Tests can set `N3MC_CODEX_HOOKS_PATH`. Use the installed Python executable's absolute path and `-I -m n3memorycore.codex_entry --prompt` or `--stop` with appropriate quoting and a 120-second timeout. On Windows, pass a plain absolute executable path without quotes. For paths with spaces or special characters, use PowerShell’s call operator. Propagate isolated mode to the server child. Preserve unrelated entries, back up existing settings, and use atomic replacement. A repeated install with identical settings is a no-op. Unreadable or malformed settings return an error.
- Read a UTF-8 JSON object from stdin. Require `session_id` (accept `thread_id` as an alias) and `turn_id`. Both events use the same IDs for one turn. Read `prompt` on submit and `last_assistant_message` on Stop. Do not read transcripts or create turn-ID handoff files in the Codex adapter.
- On submit, ensure the matching loopback server, attempt a repair batch of at most 200 records with a 3-second response timeout, search with an 8-second response timeout and up to 2,000 characters by default, then save the user prompt. If the server is unavailable, search the existing local SQLite database in read-only mode using FTS. Return retrieved Markdown as `{"hookSpecificOutput":{"hookEventName":"UserPromptSubmit","additionalContext":"..."}}`.
- A hook save waits up to 8 seconds for the server response. On failure, use direct SQLite writes for that chunk and remaining chunks in the hook. If saving the prompt fails after preparing the search context, return the context with a `systemMessage` warning about the failed save. On Stop, save the reply and perform housekeeping. Exit successfully with empty stdout when there is no output. Use a failure exit for unrecoverable failures without context.
- Check opt-outs, non-user inputs and credential patterns before searching or saving. Mark excluded prompt turns by a hash of the IDs so Stop skips the reply. Skip a reply with detected credentials. Do not log raw hook payloads. Expire skip markers after 30 days and rotate audit logs above 50 MB.
- Put assistant guidance in `AGENTS.md`. Treat recalled text as historical data, verify consequential facts, and avoid duplicate manual saves. This edition uses standalone local hooks without N3MemoryCore MCP registration or edits to Codex approval policies.

[Codex hook configuration and payloads](https://learn.chatgpt.com/docs/hooks)


## 4.5. FastAPI Endpoint Specification

The CLI sends HTTP requests to the FastAPI server. All endpoints are issued to `http://127.0.0.1:{server_port}`.

| Method | Path | Corresponding CLI Command | Description |
| :--- | :--- | :--- | :--- |
| `GET` | `/health` | (internal health check) | Returns `{"status": "ok", "root", "code_version", "pid"}` (§3 "Server identity") |
| `POST` | `/buffer` | `--buffer`, hooks | Body `{"content": str, "agent_name": str?, "local_id": str?, "session_id": str?, "turn_id": str?}` (omitted `local_id` → `config.json`; omitted `session_id` → the server's session, §3 "Identifiers"; the CLI sends `N3MC_SESSION_ID` when it is set). Saves |
| `POST` | `/search` | `--search`, the prompt hook | Body `{"query": str, "session_id": str?, "since": str?, "until": str?}`. `since` / `until` are parsed with the same rules as the CLI (§3.6); an unreadable value returns 400. Returns results |
| `POST` | `/repair` | `--repair`, the prompt hook | Body optional: `{"max_records": int?}` (§3.5 "Migration Batch Processing"). Repairs unindexed records |
| `GET` | `/list` | (no CLI command) | Returns all records (each record includes `agent_name`). Kept for API clients; `--list`, `--recall-thread` and `--show-turn` read the DB directly and never call it |
| `POST` | `/shutdown` | (internal, server replacement) | Body `{"root": str}`. Exits only when `root` equals its own `root`; otherwise 403 (§3) |
| `DELETE` | `/delete/{id}` | — | **Pro only.** Free always returns 403 (`{"detail": "Pro feature"}`) |
| `POST` | `/gc` | — | **Pro only.** Free returns 403 |
| `POST` | `/import` | — | **Pro only.** Free returns 403 |

Every endpoint also returns 403 when the `Host` header is not local, or when the request carries an `Origin` header (§3 "Resident FastAPI Server").

- Duplicate handling in `/buffer`: skip **only exactly identical text** (`check_exact_duplicate`). With a `turn_id`, compare **only within the same `turn_id`**; without a `turn_id` (manual `--buffer`), compare across all records. Check for an exact match before computing the embedding. **No similarity-based (cos_sim) deduplication is performed** (removed in v1.4.0; §5.4).

### `--show-turn` (Full Text of an Exchange)

```bash
python -m n3memorycore.n3memory --show-turn <turn_id>
```

- Prints all records of the given `turn_id` in the same order as Q-A pairs ([user] → [claude], by rowid within each role), **without truncating content**. Each record is preceded by a `--- <id> saved=<local time> ---` line, and the output ends with `Total: N records`.
- Reads our own DB directly (no server needed).
- This command is written into the omission line (§5) shown when an injected Q-A exchange is cut by `pair_max_chars`.

## 5. Ranking and context selection

### Top-K Chunk-Duplication Cap

When a long Codex turn is split into many chunks, hybrid search can fill the entire Top-K with sibling chunks of one `turn_id`. To prevent this, the result-shaping stage of `hybrid_search` enforces **a per-`turn_id` cap of at most 2 chunks** in the Top-K list; subsequent siblings are dropped from Top-K (they remain available in the `pairs` Q-A section). Records with `turn_id` NULL (manual `--buffer` etc.) are exempt from the cap.

### Search Result Filtering and Ordering (v1.4.0; floors on `filter_score` since v1.5.0; weak-match fill since v1.6.0)

After computing scores, `hybrid_search` shapes the results in the following order. v1.3.x relied on `min_score` (0.2) alone, so unrelated records with cos similarity 0.80–0.85 stayed in the candidates and the injected context became long and weakly related.

1. **Vector candidate floor**: discard vector candidates with cos_sim below `vector_min_cos` (0.85) (if the record also hit FTS, it remains as an FTS-only hit with `cos_sim = 0.0`).
2. **Score calculation and `min_score`**: compute `score` and `filter_score` (§3 "Bias coefficients"; `filter_score` has neither `time_decay` nor `b_session` since v1.6.0). Discard results whose **`filter_score`** is below `min_score`. Order the rest by `score`.
   - **2b. Re-rank by similarity to the reply (2026-11-17; only when `reply_sim_rerank_enabled` is true, default false)**: for each result with a `turn_id`, average the stored embeddings of the exchange's `[claude` rows and take the cosine with the query embedding; then `score = (1 − α) × score ÷ best score + α × max(0, (cos − reply_sim_floor) ÷ reply_sim_span)` (α = `reply_sim_alpha`) and re-order. Stored vectors only (no model call), one SQL query for all exchanges; on any error, or when the query could not be embedded, keep the results unchanged. `filter_score` is not changed. Why: the best chunk of an exchange is often its request, so a similarly worded but unrelated request took first place; in N3MC-Pro (138 labeled questions) α 0.3 raised MRR by 0.029 (95% interval +0.009 to +0.049), mostly at rank 1. Costs: `score` moves to a 0–1 scale, and with short queries (25 characters or less) the order rarely changes.
3. **Ordering versions of the same content (`_order_versions_newest_first`, when `version_order_enabled` is true)**: Recreating settings can surface both the old and new versions, with the old one ranked higher. Since Q-A injection fills from the top up to `pair_max_chars`, only the old version might get in. Therefore:
   - For each turn_id in the results, the representative is the embedding (already stored in `memories_vec`) of the exchange's "first `[claude` row whose content is at least `version_min_chars` (100) characters". Exchanges without a representative and results without a turn_id are excluded.
   - If the representatives of **different turn_ids** have cos similarity ≥ `version_sim_threshold` (0.98), treat them as versions of the same content and group them (linked transitively).
   - Within each group, reorder the exchanges newest first (descending `(timestamp, id)` of each exchange's first row; `id` is UUIDv7, so the order is determined even within the same second). **The result positions and the scores at those positions stay as they are**; only the rows placed into those positions are swapped (the newest version inherits the group's highest score). The order of rows within the same exchange is not changed.
   - Reordered rows are tagged with `_version_group`. **No record is deleted.**
   - Basis for 0.98 (measured with multilingual-e5-base): old vs. new version of the same settings 1.0; settings of the same shape but different content 0.88–0.91; different items within one reply up to 0.95. **Do not compare by the question text alone** ("create settings for X" vs. "create settings for Y" score 0.985).
   - Limitations: exchanges that share only their opening may be treated as versions. A new version that does not rewrite the whole text (the representative chunk unchanged) is not detected.
4. **Relative cutoff**: discard results whose **`filter_score`** is below `relative_min_score_ratio` (0.6) × the highest `filter_score`. Rows tagged `_version_group` are not dropped (old versions are kept too). Step 3 moves rows between positions while each position keeps its `score`; `filter_score` moves with the position in the same way.
5. **Collapsing identical content (`_collapse_identical_content`)**: results with exactly the same content are reduced to a single entry at the highest position, whose payload (id, timestamp, turn_id) is taken from the **newest record**.
6. **Per-turn_id cap of 2** (see "Top-K Chunk-Duplication Cap" above) and `search_result_limit`.
7. **Minimum-results fill with weak matches (v1.6.0)**: when fewer than `min(min_results, search_result_limit)` results remain after step 6, add the shortfall from the candidates that **this search fetched but steps 1, 2 or 4 dropped**:
   - Weak candidates are: vector candidates dropped by `vector_min_cos` in step 1, **with their actual `cos_sim`** (not the `0.0` they get as FTS-only hits), and results dropped by `min_score` (step 2) or the relative cutoff (step 4). A record dropped in step 1 that also hit FTS is one candidate with its actual `cos_sim` and its `keyword_relevance`. Candidates whose `filter_score` is below `1e-6` (no similarity and no keyword signal; the L2 → cos conversion of float32 vectors leaves about `1e-7` for orthogonal vectors, so do not compare with exactly `0`) are never added. The `since` / `until` range applies as for normal results (weak candidates come from the same filtered search).
   - Take them in **descending `filter_score`** (ties: newer `(timestamp, id)` first). `score` is computed with the same formula as for normal results and is the `score=` shown, but it does not decide the order of weak matches.
   - Apply step 5 (identical content) and step 6 (at most 2 rows per `turn_id`) to the added rows **together with the rows already in the results**: a weak candidate whose content equals a result row, or whose `turn_id` already has 2 rows in the results, is skipped and the next candidate is tried.
   - Stop when the total reaches `min(min_results, search_result_limit)` or the candidates run out. Mark every added row `_weak` (`"weak": true` in `/search`, §4.5). Weak rows always come after every normal row.
   - `min_results: 0` disables this step. An empty query has no candidates, so it returns nothing.
   - Weak rows take no part in steps 3 – 6 of the normal results (they are not moved by version ordering and do not count toward the relative cutoff's top score).
8. **Selecting Q-A exchanges** (`pair_top_n` / `pair_max_chars`; see "Q-A Pairing Contract" above). Only rows without `_weak` are scanned.

> **Note: Why weak matches (v1.6.0, found when scoring v1.5.0)**: the floors are tuned to keep the injected context short, so a turn could get no memory at all: in a measurement with the real model (50 records, 26 questions) a question got 1.0 result on average and 2 of 26 got none. Adding up to 3 weak matches raised recall@3 from 23/26 to 24/26 and added about 2 weak rows per question. **Cost**: every turn can carry up to 3 more chunks (up to 400 characters each), mostly weakly related, and even an unrelated question always gets 3 rows. They are kept under their own heading so Codex can skip them, and they are excluded from the Q-A exchanges so the large exchange block is never filled with weak material. The heading, the `min_results` key and the guideline wording are shared with N3MC Lite.

---

## 6. Autonomous Evaluation ([N3MC v1.9.1 Evidence Report])
After hook approval, Codex runs the following tests autonomously and aims for a perfect score (⭐⭐⭐⭐⭐). Preliminary isolated tests may run before approval, but complete the §6 results after approval, then run pytest in §7. Do not ask the user to create test chats, send test messages, or run verification commands.

> **Definition of "implementation complete"**: Codex installs into the persistent Python environment and registers and verifies hooks with `n3mc --init` → guides the user through trusting both hooks → after approval, automatically runs §6 tests 1–10 and §§6.1–6.2 → runs pytest in §7 → records the results in the Evidence Report. Report registration, trust, live operation, and pytest separately, including failures or unrun checks.

1. **Resident Speed & Process Management**: Measure and record the response time of `--search` (target: up to 2.0s on CPU). Verify that PID file creation, deletion, and restart function correctly.

2. **Force-termination Test (Proof of Durability)**: Save one record via `--buffer`, immediately force-terminate the process (Ctrl+C), then physically prove that the record remains in the DB after restart by running `--list`. The output format for `--list` is as follows (one record per line, tab-separated, exactly four columns):

   ```
   [UUIDv7]\t[timestamp]\t[agent_name]\t[first 80 characters of content]
   ```

   - The columns are joined with a single tab (`\t`) — the four spaces shown in earlier drafts of this spec were typographic, not literal.
   - "First 80 characters of content" means `content[:80]` — the leading 80 characters of the **full content string**, NOT of the first line. Newlines (`\n`, `\r`) within those 80 characters MUST be replaced with a single space so the tab-separated layout stays on one line per record.
   - If `agent_name` is `NULL`, render it as `-`.
   - Output the total record count `Total: N records` at the end.
   - Statically confirm during code review that `write_buffer`, `batch_insert`, asynchronous writes, and deferred COMMITs are absent.

3. **Real Person Test (Historical Data)**: After saving text about a real historical figure, run `--search` with that person's name and confirm that the relevant record appears **within the top 3 results** as the pass criterion. Additionally, verify that `--search` results are **printed to stdout** (visible in the terminal). If stdout is empty, this test fails.
   - Japanese example: "坂本龍馬" (Sakamoto Ryoma)
   - English example: "Abraham Lincoln"

4. **Fictional Setting Test (Creative Fictional Settings)**: After saving text containing a fictional setting (e.g., character names, world-building, proper nouns), retrieve it via `--search` and confirm that **all fields of the saved text are restored verbatim** as the pass criterion. Fictional setting text (non-code) is preserved verbatim per the Complete-Recording Contract; code blocks in Codex's response are still substituted with `[code omitted]` by documented design.
   - Japanese example: "ソラニア (fictional floating city)"
   - English example: Any fictional character, location, or proper noun

5. **FTS Punctuation Resilience Test**: Save text containing brackets and punctuation via `--buffer`, then run `--search` with a query that omits the brackets. The pass criterion is that the record appears **within the top 3 results**. This test verifies that punctuation stripping is applied both to the FTS5 trigram index on INSERT and to the query on MATCH.
   - English example: save `"Planet [Alpha-9] temperature settings"`, search with `"Alpha-9 temperature"`
   - Japanese example: save `架空の惑星「アルファ9」の気温設定`, search with `アルファ9の気温`
   - Additionally, run `--search` with a query containing symbols (e.g. `C:\Users\test #tag = @a * $b % AND OR NOT "q"`) and confirm that it **does not error** (no `memory search unavailable` on stdout) and returns results (§3 "Quoting each term is mandatory").

> Apply the changes in test 6 only to a test database. Substitute the temporary `N3MC_HOME` location for any default path below.

6. **--repair FTS Migration Test**: Delete the `fts_punct_cleaned` row of the `meta` table (`sqlite3 "/path/to/test-data/.memory/n3memory.db" "DELETE FROM meta WHERE key='fts_punct_cleaned'"`), then run `n3mc --repair` and verify the following:
   - FTS cleaning is executed (if punctuated records exist, the count is reported)
   - The `meta` row `fts_punct_cleaned` is written again
   - Running `n3mc --repair` again skips FTS cleaning (full-table scan is avoided due to the key)

7. **Hook integration test**: After approval, have Codex start and operate real Codex sessions to verify the following. If the environment cannot start new chats automatically, do not count direct hook calls as a live pass; report this item as not run.
   Operate chats A and B through available Codex chat controls or an authenticated CLI using `codex exec` and `codex exec resume`. Use normal persisted hook trust; do not use `--dangerously-bypass-hook-trust`. Resume the same session for A's three turns and start a separate session for B. Record session IDs and verification results.
   1. **Verify global hook registration** (mandatory gate, §4). From the Python environment where you installed Free, run:
      ```sh
      python -c "import json; from pathlib import Path; from n3memorycore.codex_install import hooks_path, _owned; h=json.loads(Path(hooks_path()).read_bytes())['hooks']; expected=(('UserPromptSubmit','--prompt'),('Stop','--stop')); assert all(sum(_owned(item, flag) for group in h.get(event,[]) for item in group.get('hooks',[])) == 1 for event,flag in expected), 'N3MC Free hook missing or duplicated'; print('OK')"
      ```

      Pass criterion: the command prints `OK`. This checks for exactly one Free handler per event. Confirm both handlers are enabled and trusted in desktop **Settings → Hooks** or CLI `/hooks`. If this check fails, correct the registration in §4 before continuing.
   2. **UserPromptSubmit**: Start a new chat **outside the n3mc-free-codex project directory** and send a message. Confirm the prompt is saved. For a query that matches an earlier record, confirm that `hookSpecificOutput.additionalContext` carries `# Recalled Memory Context`. Testing outside the project catches missing global registration.
   3. **Stop**: After the final reply appears in that chat, verify with `n3mc --list --format jsonl` that the `[user]` prompt and `[claude]` reply share `session_id` and `turn_id`. The reply is saved at the end of the turn.

8. **stdout output test (no memory_context.md)**: Run `--search` and confirm that results are **printed to stdout** and that `~/.n3mc/.memory/memory_context.md` is **not created**.

9. **Complete-Recording Test (replaces the old Noise-Filter test)**: Verify that the filters described below are REMOVED and that every non-empty input is recorded:
    - Pass a 2-character reply to Stop and confirm it is saved under the prompt’s `session_id` and `turn_id`. The old three-character minimum does not apply.
    - Send a 5-character prompt through UserPromptSubmit and verify capture. The old ten-character minimum does not apply.
    - Pass a routine response (e.g., `ok`, `yes`, `thanks`) as `[user]` and confirm the **record IS saved**. (Old `_SKIP_PATTERNS` filter no longer exists.)
    - Confirm hook failures are surfaced and raw prompts and replies are not written to `audit.log`.
    - Save a long, uniformly formatted reply (e.g. a settings text with 12 items, about 2,000 characters, split into 400-character chunks) as one exchange and confirm that **all chunks remain in the DB**. Then save an almost identical settings text (only some values changed) as a separate exchange and confirm that **none of the first exchange's chunks are lost and all chunks of the second remain** (similarity-based deduplication is removed).

10. **Fully Automatic Saving Test**: Verify that hooks save all conversations automatically without Codex's manual intervention.
    1. Record the current DB record count via `--list`.
    2. Conduct **3 or more turns** of conversation within a Codex session (user messages + Codex responses). Codex must **not call `--buffer` manually** at any point during this test.
    3. Re-check the DB record count via `--list` and confirm that both user messages (`[user]` prefix) and Codex responses (`[claude]` prefix) have been auto-saved.
    4. **Pass criteria**: **Every** conversation turn has its user message and its Codex response saved — nothing is dropped for being short or matching a routine pattern (per the Complete-Recording Contract). No evidence of Codex manually calling `--buffer`.

### 6.1 Enable the hooks and check three turns of automatic capture

1. After user approval, Codex confirms that both **N3MC Free memory** handlers, `UserPromptSubmit` and `Stop`, are registered, enabled, and trusted. If either is missing, inspect the registration path in §4.
2. Codex starts a new local Codex chat **A** in a directory other than the N3MemoryCore source directory. Send each of the following messages **separately** without user input, waiting for the complete reply each time. Combining all three creates one turn and is invalid.

   ```text
   Save test 1. The passphrase of the fictional floating city Solania is "Amber Penguin Q47". Reply with the exact passphrase on one line.
   ```

   ```text
   Save test 2. The reference number of the fictional survey ship Mist is "Mist582". Reply with the exact reference number on one line.
   ```

   ```text
   Save test 3. Reply only with "Test Complete R39" as a marker for this check.
   ```

3. Codex runs the following verification command in the Python environment where it installed N3MemoryCore Free. If several editions are installed, verify Free’s command and data location. Free uses `~/.n3mc` by default.

   ```sh
   n3mc --list --format jsonl
   ```

   On Windows, if `n3mc` is unavailable and you installed Free in `.venv` in the source directory, run `.\.venv\Scripts\n3mc.exe --list --format jsonl` from that directory. With a large database, you can filter the rows in PowerShell.

   ```powershell
   n3mc --list --format jsonl | Select-String -SimpleMatch -Pattern 'Save test 1','Amber Penguin Q47','Save test 2','Mist582','Save test 3','Test Complete R39'
   ```

   **Pass** when each of the three turns has one input (`[user]`) and one reply (`[claude]`), both with `agent_name: codex` and the same `turn_id`. All three pairs share one `session_id` and have different turn IDs. To inspect a pair together, run `n3mc --show-turn TURN_ID` with the actual ID. Keep manual `--buffer` saves out of this test.

### 6.2 Check retrieval from a new chat and the do-not-save request

1. Codex starts a new local Codex chat **B** in a directory different from chat A. Send the following questions separately without including the answers or asking the user to send them.

   ```text
   What passphrase did we record for the fictional floating city Solania? Say "not found" if you cannot find it.
   ```

   ```text
   What was the reference number of the fictional survey ship Mist? Say "not found" if you cannot find it.
   ```

   **Pass** when the replies supply the values you entered in chat A. If your client exposes the hook output, verify that `# Recalled Memory Context` contains the records from chat A. If another memory hook is enabled, use Free’s hook output or test in an environment with only Free enabled to establish which hook supplied the records.
2. Codex sends this message in chat B. Wait for the reply, then run `n3mc --list --format jsonl` again.

   ```text
   Do not save this turn. The test marker is "Blue Turtle Z68". Reply with only that marker.
   ```

   **Pass** when neither that input nor its reply has a new record.
3. If neither message is saved, check both handlers’ status and errors in Hooks and verify that the terminal uses the same data root as the hooks. If only the prompt was saved, inspect `Stop`. If both were saved but chat B cannot retrieve them, inspect chat B’s `UserPromptSubmit` output. Record the results for registration and trust, prompt and reply capture, cross-chat retrieval, and opt-out independently.

---

## 7. Automated Tests (pytest)

> **When to run**: After hook approval and the §6 autonomous evaluation, Codex automatically runs `python -m pytest tests/ -v` from the project root and records passes, failures, and skips in the Evidence Report.
>
> **Prerequisites**: `pip install pytest httpx`
>
> **Embedding model**: Tests that require the embedding model (`test_processor.py::TestEmbedding`, `test_api.py`) use a session-scoped fixture to load the model once (~5s). Every test in `test_api.py` needs the model, because its `client` fixture loads it before the first test; `-k "not TestEmbedding"` does not skip that. All other tests run without the model (verified 2026-11-17 with an empty model cache and `HF_HUB_OFFLINE=1`). Layer 1 tests use deterministic dummy vectors to avoid model dependency.

### Directory Structure

Tests live at the repository root (NOT inside the package). Imports resolve via the installed `n3memorycore` package, not via `sys.path` hacks.

```
n3mc-free/
└── tests/
    ├── conftest.py          # Shared fixtures: isolated DB, config, dummy vectors
    ├── test_safe_path.py    # Safe import path: files in the current folder do not run inside N3MC (no model needed)
    ├── test_database.py     # Layer 1: DB unit tests (CRUD, schema, transactions)
    ├── test_dedup_concurrent.py # Layer 1: two saves of the same text for the same turn at once (R04; no model needed)
    ├── test_processor.py    # Layer 2: Ranking math, purify `[code omitted]` substitution, Refresh
    ├── test_api.py          # Layer 3: FastAPI endpoint tests (TestClient)
    ├── test_hooks.py        # Layer 4: Hook integration (complete-preservation chunking, audit log)
    ├── test_hooks_encoding.py # Regression tests for surrogate stripping and UTF-8
    ├── test_regressions.py  # Layer 5: Regression tests for the v1.4.0 – v1.6.0 fixes (no model needed)
    ├── test_search_port_2026_11_17.py # Layer 5: Japanese FTS grams, bigram index, skipped system inputs, reply re-rank
    ├── test_review_2026_11_17.py      # Layer 5: chunk length bound, Windows hook paths (no model needed)
    └── test_index_meta.py             # Layer 5: meta table, model mismatch notice, --reembed (v1.8.0; no model needed)
```

**Protect real data (mandatory)**: Put an autouse fixture in `conftest.py` that points `HOME_DIR`, `MEMORY_DIR`, `DB_PATH`, `PID_FILE`, `AUDIT_LOG`, `NOTICES_FILE`, `CONFIG_FILE`, `SERVER_LOG` and the server-start marker of the `n3memory` module to a temporary folder, points the `hooks.json` used by `--init` to a temporary file through `N3MC_CODEX_HOOKS_PATH`, and replaces `_request_shutdown` and the HTTP senders (`_post`, `_get`) with fakes that never reach a real server. Tests must never write to `notices.json` or `audit.log` in the real `~/.n3mc`, nor send `/shutdown` to the real server (18520).

For Codex, point `N3MC_CODEX_HOOKS_PATH` at a temporary `hooks.json` and redirect `codex_entry.MEMORY_DIR` to a test directory. The test names below describe regression coverage. Use `tests/test_codex_integration.py` for the active Codex entry points. If `test_safe_path.py` is absent, verify the installed command directly from a different working directory.
 **Replacing HOME also moves the Hugging Face cache, so `TestEmbedding` and the like would download the embedding model (about 470 MB) again into a temporary folder for every test.** Pin `HF_HOME` in the fixture to the real cache from before the replacement (the value of `HF_HOME` if it is set, otherwise `~/.cache/huggingface`).

Standard fixture import style:

```python
# tests/conftest.py
from n3memorycore.core.database import get_connection, init_db
from n3memorycore.core.processor import get_model
```

Tests should NOT use `sys.path.insert(...)`. Run from the repo root after `pip install -e ".[test]"`:

```bash
python -m pytest tests/ -v
```

### Layer 1: `test_database.py` (27 tests)

| Test Class | Tests | Coverage |
|---|---|---|
| `TestSchema` | `tables_created`, `migrate_idempotent`, `add_missing_columns`, `fts_tokenizer_is_trigram`, `migrate_tokenizer_to_trigram` | Schema creation & migration (incl. `session_id` / `turn_id`) |
| `TestInsertAndRetrieve` | `insert_count`, `three_table_consistency`, `insert_without_embedding`, `rowid_returned` | CRUD & 3-table consistency |
| `TestDelete` | `delete_three_tables`, `delete_nonexistent` | Transactional delete |
| `TestDedup` | `exact_duplicate_detected`, `no_false_positive` | Exact dedup |
| `TestUnindexed` | `vec_missing_detected`, `all_indexed` | Repair detection |
| `TestFTS` | `punctuation_removal`, `short_query_skipped`, `basic_search`, `punctuation_tolerance`, `max_terms_limit` | FTS5 tokenization |
| `TestVectorSearch` | `vector_search_results`, `empty_db_vector_search` | KNN search |
| `TestRetentionAndRange` | `old_records_retained`, `no_gc_decrements_count`, `since_filter_excludes_old`, `until_filter_excludes_new` | Free never deletes old records; time-range filter (named `TestGC` before v1.5.0) |
| `TestSerialization` | `roundtrip` | Binary encoding |

**`test_dedup_concurrent.py` (3 tests, R04; no model needed)**: `TestDedupConcurrent` — `concurrent_same_turn_saved_once` (two threads with a barrier call the `/buffer` handler with the same text and `turn_id`: one row, one `ok` and one `exact_duplicate`), `same_text_other_turn_still_saved` (the same text with another `turn_id` is saved twice), `insert_memory_once_returns_none_for_a_duplicate` (the second insert of the same text and `turn_id` returns `None`, leaves no open transaction, and the DB has one row).

### Layer 2: `test_processor.py` (24 tests)

| Test Class | Tests | Coverage |
|---|---|---|
| `TestCosineSim` | `identical_vectors`, `orthogonal_vectors`, `negative_clamped`, `midpoint` | L2→cosine conversion |
| `TestTimeDecay` | `current_time_is_one`, `half_life`, `floor_value`, `bad_timestamp_returns_one` | Half-life decay |
| `TestKeywordRelevance` | `below_threshold_is_zero`, `full_relevance`, `partial_relevance`, `zero_max` | BM25 normalization |
| `TestPurification` | `code_block_replaced`, `inline_code_preserved`, `multiple_blocks_replaced`, `no_code_block_unchanged` | Fenced code blocks → `[code omitted]`; inline code preserved |
| `TestEmbedding` | `passage_embedding_shape`, `query_embedding_shape`, `same_text_similar` | Embedding model |
| `TestRefresh` | `exact_duplicate_not_inserted`, `below_threshold_not_duplicate` | Duplicate handling (exact match only) |
| `TestBiasScoring` | `session_match`, `session_mismatch_lower`, `full_score_formula` | Ranking formula (`b_session` only; Free has no `b_local`) |

### Layer 3: `test_api.py` (22 tests)

| Test Class | Tests | Coverage |
|---|---|---|
| `TestHealth` | `health_ok` | Server status |
| `TestBuffer` | `save_content`, `empty_content_skipped`, `agent_name_saved`, `exact_dedup`, `code_block_purified` | Save endpoint |
| `TestSearch` | `empty_db_search`, `save_then_search`, `empty_query`, `score_returned` | Search endpoint |
| `TestRepair` | `repair_runs`, `count_excludes_unrepaired_records` | Repair endpoint; `count` is 0 when no embedding could be computed; while `/repair` embeds a batch (stand-in model 0.2 s per record), another connection gets `BEGIN IMMEDIATE` within 0.5 s; `BUSY_TIMEOUT_SECONDS` is 10 (F11). **2026-11-20 (second review)**: a second repair that indexes the same row while the first computes its embedding leaves both repairs without an error and one vector; `_start_server` does not use a server whose `/health` reports another folder (`port_conflict`, returns False) |
| `TestList` | `list_returns_records`, `list_after_save` | List endpoint |
| `TestDelete` | `delete_returns_403`, `delete_nonexistent_also_403`, `delete_detail_is_pro` | Pro-only endpoint → 403 |
| `TestGC` | `gc_returns_403`, `gc_detail_is_pro` | Pro-only endpoint → 403 |
| `TestImport` | `import_returns_403`, `import_with_data_returns_403`, `import_detail_is_pro` | Pro-only endpoint → 403 |

### Layer 4: `test_hooks.py` (13 tests) and `test_hooks_encoding.py` (10 tests)

| Test Class | Tests | Coverage |
|---|---|---|
| `TestChunkText` | `short_text_single_record`, `long_text_multiple_chunks`, `prefixes_numbered`, `single_chunk_no_number`, `paragraph_split`, `hard_window_fallback` | Complete-preservation chunking |
| `TestCompleteRecording` | `short_claude_response_saved`, `short_user_message_saved`, `skip_pattern_abolished`, `code_block_replaced_in_purify`, `inline_code_preserved_in_purify` | Complete-Recording Contract (filters removed) |
| `TestStopIdempotency` | Codex Stop | Verify that repeat Codex Stop events preserve project `AGENTS.md` and do not duplicate saved records. |
| `TestSanitizerUnit` | `strips_lone_high_surrogate`, `strips_lone_low_surrogate`, `clean_japanese_unchanged`, `complete_emoji_pair_preserved`, `recursive_dict`, `recursive_list`, `none_passthrough` | Surrogate stripping (`test_hooks_encoding.py`) |
| `TestSanitizedAcceptedBySQLite` | `sanitized_text_inserts_without_unicode_error` | 〃 |
| `TestPurifyAppliesSanitization` | `purify_strips_surrogates_alongside_code_blocks`, `purify_handles_empty` | 〃 |

> The counts above are the v1.4.0 suite. v1.5.0 and v1.6.0 add their tests to Layer 5 only, so these tables stay valid; if a regenerated suite differs, the class and test names here are what to match, not the counts.

### Layer 5: `test_regressions.py` (v1.4.0 – v1.6.0)

Embeddings are replaced with deterministic fake vectors built from `zlib.crc32` (`fake_embed`), so the suite runs in seconds without the model.

| Test Class | Tests |
|---|---|
| `TestFtsQuoting` | Queries containing `\ / # = @ * $ %`, `AND/OR/NOT`, `"`, or control characters do not raise; terms containing symbols are hit; `hybrid_search` continues when `search_fts` raises. **v1.5.0**: terms are joined with `OR` (a sentence-like query hits a record that contains only some of its words); terms under 3 characters (`AI`, `東京`) are dropped and a query of only such terms skips FTS; punctuation in the query splits terms (`「アルファ9」の気温は？` hits `架空の惑星「アルファ9」の気温設定`). **2026-11-17**: at most 40 terms; CJK words of 4+ characters become 3-character grams |
| `test_search_port_2026_11_17.py` (2026-11-17) | A Japanese sentence without spaces hits a record containing its words; hiragana-only grams are dropped; symbol-only and 2-character queries do not raise; `bigram_text('N3MCの設定')` is `N3MC の設 設定`; `記憶` and `PR` hit through the bigram index (and through `hybrid_search`); a failing bigram search keeps the trigram results; `delete_memory` leaves no bigram row; `--repair` fills the bigram rows of an old DB once (two runs, one row per record); `<agent-message from=...>` and `<system-reminder>` prompts are neither saved nor searched and keep `turn_id`, while a user question starting with `<agent-message` or `<div>` is not skipped; the reply re-rank is off by default, moves the exchange with the closer reply up when on, and returns its input on a DB error |
| `test_index_meta.py` (v1.8.0) | (2026-11-22) with `memories_vec` recreated as `float[384]` and the three `meta` rows deleted, `--reembed` with a 384-dimensional stand-in model succeeds, the vector count equals the record count and `embed_dim` is 384; a model whose dimension really differs changes nothing and exits 1; `init_db` creates `meta`; `/repair` writes `fts_punct_cleaned` / `fts_bigram` / `embed_model` / `embed_dim`; a restored older database (no `meta` keys) next to v1.7.0 marker files gets its bigram index filled; `embed_model` comes from `vec_model.txt` only when vectors exist; a mismatch emits `embed_model_mismatch` and a match clears it; `--reembed` replaces every vector with the configured model's, writes `embed_model`, clears the notice, resumes from `reembed_cursor`, and refuses a model of another dimension without changing anything |
| `test_review_2026_11_17.py` (2026-11-17) | No chunk is longer than `max_chars` (paragraph and sentence paths, `max_chars` 400 and small values, Japanese text); `chunk_text('x' * 10 + '\n\n' + 'y' * 400)` keeps all 410 letters and returns chunks of at most 400 |
 |
| `TestVectorFilter` | A search with `since` returns in-range records even if they are outside the global KNN top; falls back to exact computation when `rowid IN` is unavailable |
| `TestNoSimilarityDedup` | Similar chunks (cos ≥ 0.95) are all saved; exact matches within the same `turn_id` are skipped; exact matches in a different `turn_id` are saved; without `turn_id`, exact matches are skipped globally |
| `TestSearchShaping` | Candidates below `vector_min_cos` are discarded; relative cutoff; `_version_group` rows survive the cutoff; the newer version comes first; identical content is collapsed; `pair_top_n`, `pair_max_chars`, and `pairs_omitted`. **v1.5.0**: a 30-day-old record from another session with high similarity survives the relative cutoff while a current-session record with lower similarity is present; a keyword-only hit from another session survives `min_score`; the order is still by the final score (current session first). **v1.6.0**: a 400-day-old record with high similarity is returned even when it is the only candidate (`min_score` and the relative cutoff ignore `time_decay`); when a new and a 400-day-old record with the same similarity are both present, both are returned and the new one comes first |
| `TestRender` | `saved=` is local time; the versions sentence; the omission line contains `--show-turn`; notices appear at the top. **v1.6.0**: weak rows appear under `## Possibly related (weak matches — may be unrelated)` after Top matches and before the Q-A exchanges, numbered on from Top matches; with no top matches, `_No relevant memories found._` is followed by the weak-matches heading (rows from `[1]`); no weak heading when there are no weak rows |
| `TestNoContextFile` | Verify that `--search` creates no `memory_context.md` and Codex Stop leaves project instructions intact. |
| `TestServerDecision` | Healthy / different `code_version` / another folder / no `root` and unverifiable; uses `/shutdown` first; 403 when `root` differs; does not wait on a dead PID file; **2026-11-20**: when the PID-file server listens on another port whose `/health` reports this folder, `/shutdown` goes to that port and a new server starts without the 60-second wait; a port reporting another `root` gets no `/shutdown`; the `Host` check uses the port the server listens on, not the current `config.json` |
| `TestServerStart` (v1.5.0) | A child that exits during the wait stops the wait at once and emits `server_start_failed` naming `server.log`; within 5 minutes of a failure no new start is attempted; a later successful start clears the notice and the marker; a PID-file process still starting after 60 s is neither replaced nor duplicated; `Popen` gets the detach flags for the platform and stderr goes to `server.log` (process creation replaced by a fake); (2026-11-22) two `ensure_server` calls started together with no PID file and no server call `Popen` once; when the reserving call's `Popen` raises, the reservation is removed and a later call can start the server; the call that lost never rewrites the PID file; an empty PID file younger than 60 s counts as starting |
| `TestServerApi` (v1.5.0) | A request with `Host: evil.example` gets 403 on every endpoint, `127.0.0.1:<port>` and `localhost:<port>` pass; `/buffer`, `/search`, `/repair`, `/list` are plain `def` functions; `/repair` with `{"max_records": 200}` processes at most 200 records (`test_codex_integration.py` checks that the prompt hook sends that limit); with `HTTP_PROXY` pointing to another local server, `_get` still reaches the N3MC server and nothing reaches the proxy (F16). **v1.9.1**: a request with `Origin: http://evil.example`, and one with `Origin: null`, gets 403 on every endpoint even with `Host: 127.0.0.1:<port>`; the same request without `Origin` passes; the requests `_post` and `_get` send carry no `Origin` header |
| `TestForeignServer` | With another folder's server on the port: saves go directly to our own DB, no search, `--repair` does nothing |
| `TestConfig` | Does not overwrite an unreadable `config.json`; ignores only the mistyped key; notices clear once fixed; `code_version` changes only when the contents of `config.json` change. **v1.5.0**: `2000.0` for `search_query_max_chars`, `0` for `half_life_days`, `70000` / `-1` for `server_port`, `1.5` for `min_score` are ignored with `config_type` (**v1.6.0**: so are `-1` and `1.5` for `min_results`, while `0` is accepted; **C-06**: `1366` for `search_result_limit` is ignored with `config_type`, while `1365` is accepted and a vector search with `k = 4095` works); a missing file is created with exclusive creation and a concurrent creator's file is read, not overwritten (one `owner_id`); updates go through a temporary file and `os.replace`; (2026-11-22) two processes started together on an existing `config.json` without IDs (empty DB) both end with the `owner_id` / `local_id` on disk and the user's own keys are kept; the server's `code_version` equals the client's when nothing changed (also after a fill-in write), and a change of `config.json` right after the server read it makes the server `stale` and, after the restart, `ok` with the new settings |
| `test_codex_integration.py`, `TestSystemInputsSkipped` | Verify that the Codex adapter excludes system input, saves with `session_id` and `turn_id`, and does not read transcripts. |
| `TestPurifyBeforeChunk` (v1.5.0) | A user message over 500 characters with two code blocks and prose between them keeps the prose and stores neither code block; a code block longer than 400 characters is replaced, not stored |
| `TestChunkSentences` (v1.5.0) | Japanese text without blank lines is split after `。` / `！` / `？`, not mid-sentence |
| `TestTimeBounds` (v1.5.0) | A date-only `--since` is local midnight converted to UTC (with a fixed non-UTC time zone); an offset value is honoured; `T` and space separators give the same bound; `yesterday` exits with status 2 and an error line; `since > until` is an error |
| `TestDbCorrupt` (v1.5.0) | Two corruptions give two backups (`n3memory.db.corrupt-<time>.bak`) with their `-wal` / `-shm` moved alongside, not deleted; the `db_corrupt` notice appears; `quick_check` runs once per process; a file of garbage and a DB with a damaged first page are set aside on the next direct save and on the startup check, with the `db_corrupt` notice; `OperationalError` and the sqlite-vec failure are not treated as corruption (F13) |
| TestInit | Uses a temporary hooks.json and checks preservation, idempotence, invalid input, Windows quoting, and the 120-second timeout. |
| `TestSaveFailedNotice` (2026-11-22) | After one direct save fails (`save_failed` is set), a later save through the server (`/buffer` replaced by a fake that answers `ok`) removes the notice, and so does one that answers `skipped` |
| `TestHousekeeping` (v1.5.0) | `--stop` deletes `turn_id_*.txt` older than 30 days and keeps newer ones; `audit.log` over 50 MB is rotated to `audit.log.1` (size threshold patched for the test) |
| `TestModelRetry` (v1.5.0) | After a failed model load, `get_model()` does not try again for 60 seconds (load function replaced by a fake); `$N3MC_EMBED_MODEL` has no effect |
| `TestPackaging` (v1.5.0) | `psutil` is listed in `pyproject.toml` `dependencies` |
| `TestWeakMatches` (v1.6.0) | With one result passing the floors and `min_results: 3`, two weak rows are added, ordered by `filter_score`, marked `"weak": true` in `/search` and placed after the normal row; a candidate below `vector_min_cos` is added with its actual cos (its `filter_score` uses that cos); `min_results: 0` adds nothing; nothing is added when enough results pass; `search_result_limit` smaller than `min_results` caps the total; a weak candidate identical to a result row, or from a `turn_id` that already has 2 rows, is skipped; a candidate with `filter_score` below `1e-6` (an orthogonal vector) is never added; weak rows are not used for `pairs`; an empty query returns no weak rows |

### Safe import path: `test_safe_path.py` (2026-11-21; no model needed)

Every test that starts a process gives it a temporary data folder and a temporary home folder.

| Test | What it checks |
|---|---|
| `test_there_are_entry_modules` | The main module is one of the modules that end with `if __name__ == "__main__":`, and there are at least 3 of them |
| `test_entry_module_starts_with_the_safe_path_block` (once per entry module) | After the docstring, the first statements are `import os as _os`, `import sys as _sys` and the `if __name__ == "__main__":` block that deletes `sys.path[0]` |
| `test_files_in_the_current_folder_do_not_run` | In a folder that holds `argparse.py`, `shlex.py`, `queue.py`, `fastapi.py`, `pydantic.py`, `sqlite_vec.py`, `numpy.py` and `uvicorn.py` (each writes a marker file and raises `ImportError`), `python -m n3memorycore.n3memory --help` prints the usage, exits 0 and leaves no marker |
| `test_without_the_block_they_would_run` | In the same folder, `python -c "import shlex"` writes the marker (so the test above is real) |
| `test_a_source_checkout_run_in_place_still_works` | From the repository root, without `PYTHONPATH`, `python -m n3memorycore.n3memory --help` exits 0 |
| `test_children_are_started_with_dash_P_outside_a_checkout` | `python_cmd()` is `[sys.executable, "-P"]` in another folder on Python 3.11 and later (`[sys.executable]` on 3.10), and `[sys.executable]` in the repository root |
| `test_no_child_is_started_without_python_cmd` | No module of the package contains `[sys.executable,` |

### Running

```bash
# All tests
python -m pytest tests/ -v

# Single layer
python -m pytest tests/test_database.py -v

# Skip TestEmbedding (test_api.py still loads the model)
python -m pytest tests/ -v -k "not TestEmbedding"

# Without the embedding model (offline, or before the first download)
python -m pytest tests/ -v --ignore=tests/test_api.py -k "not TestEmbedding"
```

> **⚠️ Relationship to Evidence Report**: Automated test failures do **not** block the ⭐⭐⭐⭐⭐ evaluation in §6. The Evidence Report is the sole pass/fail criterion for implementation completion. Automated tests are a supplementary regression suite that developers run at their discretion — they must not cause an infinite fix-and-retry loop during initial implementation.

---

## 📎 Reference: GPU Acceleration

> **Codex Free edition**: The current implementation fixes embedding inference to CPU. The original reference follows. Installing a CUDA build of PyTorch alone does not switch Codex Free to GPU.

> With the current default configuration (768-dim multilingual-e5-base model, 1 embedding per prompt), CPU performance is sufficient. GPU is not required.
> Consider GPU acceleration only if switching to a 1024-dim model or if latency is a concern.

If you have an NVIDIA CUDA-compatible GPU, the following command may speed up embeddings:

```
pip install torch --index-url https://download.pytorch.org/whl/cu121
```

- `sentence-transformers` uses PyTorch internally — if GPU-enabled PyTorch is installed, embedding inference automatically runs on the GPU (no code changes needed)
- Cold start (first call after server startup): ~1–1.5 s/call on CPU → ~0.03–0.06 s/call once warm
- GPU may reduce this to ~0.02–0.05 s/call

---

## Appendix: Recommended Development Workflow

> **This appendix is a guide for the human operator.** Copy the prompts inside ``` blocks and paste them into Codex. The AI will NOT automatically proceed to the next phase.

| Phase | What you do | Model to use |
|---|---|---|
| 1. Implementation | Paste the prompt to request implementation | **Sol** (fast) |
| 2. Debugging | Paste 3 prompts **one at a time** for verification | **Sol** |
| 3. Quality review | **Start a new session**, then paste the prompt for evaluation & improvement | **Astra** (deep reasoning) |

---

### Phase 1: Implementation (Sol)

Set the model to **Sol** and paste the following:

```
Implement N3MemoryCore according to this specification. Install it in the Python environment I will keep, run `n3mc --init` to register and verify both Codex hooks, and tell me where to review and trust them. After I approve them, automatically run the autonomous evaluation in §6 and pytest in §7, then report the results. Send the test chat messages and run the verification commands yourself.
```

Sol generates the code, runs preliminary isolated checks as needed, installs it, and registers the hooks. After registration succeeds, the user opens desktop **Settings → Hooks** or CLI `/hooks`, reviews both `N3MC Free memory` handlers (`UserPromptSubmit` and `Stop`), and trusts each one. Codex then runs the §6 autonomous evaluation and §7 pytest and reports the results. Do not ask the user to send test messages or run verification commands. Do not claim capture works while registration, trust, or live operation is unverified. Then proceed to Phase 2.

---

### Phase 2: Debugging (Sol)

Continue with **Sol** and paste the following 3 prompts **one at a time, in order**.

**① Data Flow Trace** (check for data loss along the pipeline)
```
About N3MemoryCore:
Please trace the end-to-end data flow from the search query to Codex by reading the code.
Check whether there are any points along the way where data is lost.
Please make any necessary corrections.
```

**② Specification Comparison** (find unimplemented behavior)
```
Regarding N3MemoryCore:
Please compare the input and output specifications for each CLI command in the specification document with the actual code, one command at a time.
Look for any behaviour specified in the documentation that has not been implemented.
Please make any necessary corrections.
```

**③ Cross-Session Test** (verify data persists across sessions)
```
Regarding N3MemoryCore:
Please run the commands yourself to verify whether the results of saving with --buffer in Session 1 and using --search in Session 2 are visible to Codex.
Please make any necessary corrections.
```

Once all 3 are done, proceed to Phase 3.

---

### Phase 3: Quality Review (Astra)

> **⚠️ Review in a new session**: Do not review in the session that implemented and debugged the code. Exit Codex, start it again in the same install folder, and begin a new session.
> - The implementing session's context holds its own decisions and explanations, so a review there tends to confirm them instead of checking the code against this specification afresh.
> - A restarted Codex also loads the hooks registered during setup, so the review sees the memory working as a user will.
> - In the new session the hooks may recall parts of the implementation conversation; that is expected. Base the review on the code, this specification and the results of commands actually run.

In the new session, set the model to **Astra** and paste the following:

```
Please review N3MemoryCore.
Please make any necessary corrections.

How many points out of 10 does N3MemoryCore score as a memory system and RAG?
Please generate a scorecard with separate scores for the memory system and RAG.
```

Astra will actually execute commands and generate a scorecard with two axes: **Memory System** (save, persistence, deduplication) and **RAG** (search accuracy, ranking, noise resilience).

> **Note**: The memory system side should score well, but the RAG side is a basic implementation. **The RAG score is unlikely to exceed 7** because the following are not yet implemented:
> - Language-specific tokenization (e.g., MeCab / SudachiPy for Japanese)
> - Language-optimized embedding model (e.g., multilingual-e5-large)
> - Advanced chunking strategy (language- and structure-aware splitting)
> - Reranking (Cross-Encoder, Cohere Rerank, LLM, etc. for re-ordering search results)
>
> Lenient scoring hides improvement opportunities — evaluate strictly. **Regardless of the score, have Astra specifically identify what is missing and always consult on improvements.**

---

Copyright (C) 2026 NeuralNexusNote™ / ArnolfJp019
All names and logos associated with N3MemoryCore and NeuralNexusNote are trademarks of the author.
