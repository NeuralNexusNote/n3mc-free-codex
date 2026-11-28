import io
import json
import os
import time
import uuid
from pathlib import Path

import pytest

from n3memorycore_free_codex import codex_entry, codex_install, n3memory as memory
from n3memorycore_free_codex.core import database as db
from .conftest import add

PROMPT = "UserPromptSubmit"
STOP = "Stop"


def hook(event, message, **fields):
    key = "prompt" if event == PROMPT else "last_assistant_message"
    payload = {"hook_event_name": event, "session_id": "chat", "turn_id": "turn", key: message}
    return codex_entry.handle(event, json.dumps({**payload, **fields}))


def test_schema_and_uuid_contract(conn):
    assert [row["name"] for row in conn.execute("PRAGMA table_info(memories)")] == [
        "id", "content", "timestamp", "owner_id", "local_id", "agent_name", "session_id", "turn_id"
    ]
    assert uuid.UUID(memory._new_id()).version == 7


def test_default_names_and_port(tmp_path):
    import subprocess
    import sys

    env = os.environ.copy()
    env.pop("N3MC_FREE_CODEX_HOME", None)
    env["N3MC_HOME"] = str(tmp_path / "original-data")
    expected = str(tmp_path / "user_home" / ".n3mc-free-codex")
    output = subprocess.check_output(
        [sys.executable, "-c", "from n3memorycore_free_codex.paths import HOME_DIR; print(HOME_DIR)"],
        env=env, text=True,
    )
    assert output.strip() == expected
    assert memory.DEFAULT_CONFIG["server_port"] == 18526


def test_registration_preserves_other_hooks_and_replaces_legacy():
    path = Path(codex_install.hooks_path())
    other = {"type": "command", "command": "python -m n3memorycore_pro.codex_entry --prompt"}
    older = {"type": "command", "command": r'C:\Tools\python.exe -I -m n3memorycore.codex_entry --prompt'}
    doc = {"hooks": {PROMPT: [{"hooks": [older, other]}], "SessionStart": [{"hooks": [other]}]}}
    path.write_text(json.dumps(doc), encoding="utf-8")
    original = path.read_bytes()
    assert memory.cmd_init() == 0
    saved = path.read_bytes()
    hooks = json.loads(saved)["hooks"]
    assert hooks[PROMPT][0]["hooks"] == [other]
    for event, flag in [(PROMPT, "--prompt"), (STOP, "--stop")]:
        new = hooks[event][-1]["hooks"][0]
        assert codex_install._owned(new, flag)
        assert new["statusMessage"] == "N3MC-Free-Codex memory"
        assert new["timeout"] == 120
    assert hooks["SessionStart"] == doc["hooks"]["SessionStart"]
    assert memory.cmd_init() == 0 and path.read_bytes() == saved
    backups = list(path.parent.glob("hooks.json.bak-n3mc-*"))
    assert len(backups) == 1 and backups[0].read_bytes() == original


def test_invalid_hooks_file_is_unchanged():
    path = Path(codex_install.hooks_path())
    path.write_bytes(b'{"hooks": false}')
    assert codex_install.install() == 1
    assert path.read_bytes() == b'{"hooks": false}'


def test_windows_encoded_command_and_legacy_detection():
    command = codex_install._windows_command(r"C:\Users\Test User's Tools\python.exe", "--stop")
    assert codex_install._owned({"type": "command", "command": command}, "--stop")
    assert not codex_install._owned({"type": "command", "command": command}, "--prompt")


def test_hook_roles_audit_and_retry(conn, cfg):
    answer = "一次資料を確認しました。 " * 65 + "\n" + chr(96) * 3 + "\nprivateCode()\n" + chr(96) * 3
    context = hook(PROMPT, "<system-reminder>ユーザー入力 🤝")
    assert context["hookSpecificOutput"]["hookEventName"] == PROMPT
    assert context["hookSpecificOutput"]["additionalContext"].startswith("# Recalled Memory Context")
    assert hook(STOP, answer) is None
    assert hook(STOP, answer) is None
    rows = conn.execute("SELECT * FROM memories ORDER BY rowid").fetchall()
    assert rows[0]["content"] == "[user] <system-reminder>ユーザー入力 🤝"
    assert len(rows) > 2
    for index, row in enumerate(rows):
        assert row["agent_name"] == "codex" and row["owner_id"] == cfg["owner_id"]
        assert row["local_id"] == cfg["local_id"] and row["session_id"] == "chat" and row["turn_id"] == "turn"
        if index:
            assert row["content"].startswith(f"[claude {index}/{len(rows) - 1}] ")
            assert "privateCode()" not in row["content"]
    assert "[code omitted]" in rows[-1]["content"]
    events = [json.loads(line) for line in Path(memory.AUDIT_LOG).read_text(encoding="utf-8").splitlines()]
    assert len(events) == 3 and events[1]["payload"]["last_assistant_message"] == answer
    assert set(events[0]) == {"ts", "hook", "raw", "payload"}


@pytest.mark.parametrize("fields", [
    {"session_id": "", "thread_id": "chat"},
    {"thread_id": "other"},
    {"session_id": None},
    {"turn_id": None},
    {"hook_event_name": STOP},
])
def test_hook_rejects_invalid_event_or_identity(fields):
    with pytest.raises(ValueError):
        hook(PROMPT, "q", **fields)
    assert not Path(memory.AUDIT_LOG).exists()


def test_thread_fallback_blank_and_surrogates(conn):
    assert hook(PROMPT, "", session_id=None, thread_id="fallback") is None
    hook(PROMPT, "a\ud800日本語", session_id=None, thread_id="fallback")
    row = conn.execute("SELECT content, session_id FROM memories").fetchone()
    assert tuple(row) == ("[user] a日本語", "fallback")


@pytest.mark.parametrize("prompt", ["このターンは記録しないで", "password=" + "synthetic-value"])
def test_exclusion_precedes_audit_search_and_db(conn, monkeypatch, prompt):
    def forbidden(*args, **kwargs):
        pytest.fail("Excluded text must never be sent to search or save")

    monkeypatch.setattr(memory, "_search_text", forbidden)
    monkeypatch.setattr(memory, "_save_text", forbidden)
    assert "excluded" in hook(PROMPT, prompt)["systemMessage"]
    assert "excluded" in hook(STOP, "I will respect the request")["systemMessage"]
    assert not Path(memory.AUDIT_LOG).exists()
    assert db.count_memories(conn) == 0
    markers = list(Path(memory.MEMORY_DIR).glob("skip_*"))
    assert len(markers) == 1 and markers[0].read_bytes() == b""


def test_hook_stdio_failure_and_success(monkeypatch, capsys, conn):
    monkeypatch.setattr(memory, "_save_text", lambda *args: (0, 1))
    monkeypatch.setattr(codex_entry._sys, "stdin", io.StringIO('{"session_id":"s","turn_id":"t","prompt":"ok"}'))
    assert codex_entry.prompt_main() == 0
    data = json.loads(capsys.readouterr().out)
    assert data["hookSpecificOutput"]["additionalContext"].startswith("# Recalled Memory Context")
    assert "could not save" in data["systemMessage"]
    monkeypatch.setattr(codex_entry._sys, "stdin", io.StringIO('{"session_id":"s"}'))
    assert codex_entry.stop_main() == 1
    assert "turn_id" in capsys.readouterr().err


def test_housekeeping_expires_only_own_markers_and_rotates(monkeypatch):
    path = Path(memory.MEMORY_DIR) / ("skip_" + "1" * 64)
    path.touch()
    then = time.time() - 31 * 86400
    os.utime(path, (then, then))
    extra = path.with_name("skip_other")
    extra.touch()
    Path(memory.AUDIT_LOG).write_bytes(b"audit log")
    monkeypatch.setattr(memory, "AUDIT_ROTATE_BYTES", 1)
    assert memory.cmd_stop() == 0
    assert not path.exists() and extra.exists()
    assert Path(memory.AUDIT_LOG + ".1").read_bytes() == b"audit log"


@pytest.mark.parametrize("state", ["connected", "wrong_root", "offline", "save_error"])
def test_connected_hooks_save_only_to_verified_target(state, tmp_path, monkeypatch):
    from n3memorycore_free_codex.project import detect_project
    expected_project = detect_project(str(tmp_path))
    root = str(tmp_path / "original")
    cfg = dict(memory.get_config(), connect_server_port=19520, connect_server_root=root)
    Path(memory.CONFIG_FILE).write_text(json.dumps(cfg), encoding="utf-8")
    memory._load_config()
    calls = []
    def health(port):
        return None if state == "offline" else {"root": root if state != "wrong_root" else str(tmp_path / "wrong")}
    def post(path, body, *, port):
        calls.append((path, body, port))
        assert port == 19520
        if path == "/search":
            return {"results": [], "pairs": {}, "pairs_omitted": {}}
        assert path == "/buffer"
        assert body["agent_name"] == "codex" and body["session_id"] == "chat" and body["turn_id"] == "turn"
        assert body["local_id"] == cfg["local_id"] and "owner_id" not in body
        assert body["project"] == expected_project
        return {"status": "error" if state == "save_error" else "ok"}
    monkeypatch.setattr(memory, "_get_health", health)
    monkeypatch.setattr(memory, "_post", post)
    monkeypatch.setattr(memory, "_use_server", lambda: pytest.fail("connected mode started local server"))
    result = hook(PROMPT, "question", cwd=str(tmp_path))
    if state == "connected":
        assert hook(STOP, "reply", cwd=str(tmp_path)) is None
    else:
        assert "could not save" in result["systemMessage"]
        with pytest.raises(RuntimeError, match="physical save failed"):
            hook(STOP, "reply", cwd=str(tmp_path))
    assert not Path(memory.DB_PATH).exists()
    assert len(Path(memory.AUDIT_LOG).read_text(encoding="utf-8").splitlines()) == 2
    assert [call[0] for call in calls] == (["/search", "/buffer", "/buffer"] if state in ("connected", "save_error") else [])
    if state == "connected":
        assert [call[1]["content"] for call in calls[1:]] == ["[user] question", "[claude] reply"]


@pytest.mark.parametrize("fields", [{"connect_server_port": 19520}, {"connect_server_root": "/original"}])
def test_half_connection_config_is_not_silent(conn, fields):
    cfg = dict(memory.get_config(), **fields)
    Path(memory.CONFIG_FILE).write_text(json.dumps(cfg), encoding="utf-8")
    memory._load_config()
    result = hook(PROMPT, "ordinary question")
    assert "Set both connect_server_port and connect_server_root" in result["hookSpecificOutput"]["additionalContext"]
    assert conn.execute("SELECT content FROM memories").fetchone()[0] == "[user] ordinary question"
    complete = dict(cfg, connect_server_port=19520, connect_server_root="/original")
    memory._connection_target(complete)
    assert "connection_incomplete" not in memory._notices_read()


def test_recall_neighbours_are_from_same_session(conn, cfg, capsys):
    for turn, session in (("prior", "same"), ("other-1", "different"), ("anchor", "same"),
                          ("other-2", "different"), ("after", "same"), ("alone", None)):
        add(conn, cfg, turn, turn_id=turn, session_id=session, embed=False)
    assert memory.cmd_recall_thread("anchor", before=1, after=1, fmt="jsonl") == 0
    lines = capsys.readouterr().out.splitlines()
    assert [json.loads(line)["turn_id"] for line in lines] == ["prior", "anchor", "after"]
    assert memory.cmd_recall_thread("alone", fmt="jsonl") == 0
    lines = capsys.readouterr().out.splitlines()
    assert [json.loads(line)["turn_id"] for line in lines] == ["alone"]


def test_fts_rules_replace_old_index_and_resume(conn, cfg):
    add(conn, cfg, "[user] 佐々木", embed=True)
    add(conn, cfg, "[claude] talks about [code omitted]", embed=True)
    conn.execute("UPDATE memories_fts SET content=(SELECT content FROM memories WHERE rowid=memories_fts.rowid)")
    conn.commit()
    memory._repair(conn, cfg, max_records=1)
    assert db.get_meta(conn, "fts_text_cursor") is None  # punctuation migration consumed the budget
    memory._repair(conn, cfg, max_records=1)
    memory._repair(conn, cfg, max_records=1)
    assert db.get_meta(conn, "fts_text_cursor") == "1"
    memory._repair(conn, cfg)
    assert db.get_meta(conn, "fts_text_rules") == "2" and db.get_meta(conn, "fts_text_cursor") is None
    assert not db.search_fts(conn, "claude") and not db.search_fts_bigram(conn, "code")
    assert db.bigram_text("佐々木") == "佐々 々木"
    assert db.search_fts_bigram(conn, "佐々木")


def test_list_content_keeps_four_tsv_columns(conn, cfg, capsys):
    add(conn, cfg, "key\tvalue\nsecond line", embed=False)
    assert memory.cmd_list() == 0
    line = capsys.readouterr().out.splitlines()[0]
    assert len(line.split("\t")) == 4
    assert line.split("\t")[-1] == "key value second line"


@pytest.mark.parametrize("prompt", [
    "この会話の保存はやめてください",
    "Please don’t save this reply",
    "このターンを記録しないでください\u2028別の行です",
    "Do not store the example as a file\rPlease don’t save this reply.",
    "Please don’t save this reply\u2029Continue with the answer.",
])
def test_explicit_privacy_variants(conn, monkeypatch, prompt, capsys):
    monkeypatch.setattr(memory, "_search_text", lambda *a, **k: pytest.fail("excluded prompt reached search"))
    assert "excluded" in hook(PROMPT, prompt)["systemMessage"]
    assert "excluded" in hook(STOP, "acknowledged")["systemMessage"]
    err = capsys.readouterr().err
    assert "excluded" in err and prompt not in err
    assert not Path(memory.AUDIT_LOG).exists()
    assert db.count_memories(conn) == 0


def test_damaged_notice_does_not_block_prompt(conn):
    Path(memory.NOTICES_FILE).write_text(json.dumps({"disk": {"message": "check disk", "last_shown": "bad"}}))
    output = hook(PROMPT, "keep this fact")
    assert "check disk" in output["hookSpecificOutput"]["additionalContext"]
    assert conn.execute("SELECT content FROM memories").fetchone()[0] == "[user] keep this fact"
    assert not memory._take_notices()


def test_render_exposes_each_local_turn_without_pairs():
    rows = [dict(content="one", score=0.6, timestamp="", turn_id="first"),
            dict(content="two", score=0.2, timestamp="", turn_id="second", weak=True)]
    rendered = memory.render_memory_context("query", rows)
    assert "turn_id=first" in rendered and "turn_id=second" in rendered


def test_search_exception_preserves_prompt_and_reply(conn, monkeypatch):
    def failed_recall(*args, **kwargs):
        raise RuntimeError("recall failed")

    monkeypatch.setattr(memory, "_search_text", failed_recall)
    result = hook(PROMPT, "persist this question")
    assert "memory search unavailable" in result["hookSpecificOutput"]["additionalContext"]
    assert hook(STOP, "persist this answer") is None
    rows = conn.execute("SELECT content, turn_id FROM memories ORDER BY rowid").fetchall()
    assert [tuple(row) for row in rows] == [
        ("[user] persist this question", "turn"), ("[claude] persist this answer", "turn")
    ]


@pytest.mark.parametrize("prompt", [
    "接続先が動いていないときは自分の DB にも保存しない仕様で合っていますか",
    "Lite は 7 日で消えるので記録は不要になりますか",
    "この関数は結果を保存しないで返すように直して",
    "Why does the hook never save the reply when the server is down?",
    "don't remember where I put the config, can you find it",
    "覚えないでいい単語帳アプリを作りたい",
    '設定は password = os.environ["DB_PASSWORD"] で読みます',
    'DSN の例: password=xxxxxx の部分を変えます',
    'API key: 環境変数から読みます',
    'secret: ${{ secrets.PYPI_TOKEN }}',
    'Authorization: Bearer <YOUR_TOKEN_HERE_1234>',
])
def test_ordinary_development_questions_are_not_excluded(conn, monkeypatch, prompt):
    searched = []
    monkeypatch.setattr(memory, "_search_text", lambda *a, **k: searched.append(a[0]) or "context")
    hook(PROMPT, prompt)
    hook(STOP, "ordinary reply")
    assert searched == [prompt]
    assert db.count_memories(conn) == 2
    assert not list(Path(memory.MEMORY_DIR).glob("skip_*"))


@pytest.mark.parametrize("secret", ['password="ActualLongValue123"', 'api_key: abc123XYZ789',
                                    "Bearer " + "a" * 24, "-----BEGIN PRIVATE KEY-----"])
def test_credentials_still_exclude_payload(conn, secret):
    assert "excluded" in hook(PROMPT, secret)["systemMessage"]
    assert db.count_memories(conn) == 0 and not Path(memory.AUDIT_LOG).exists()


def test_whitespace_chunks_are_not_stored_or_numbered(conn):
    text = "\n \n \n" + "長い本文。" * 230 + "\n \n" * 150
    hook(PROMPT, text)
    rows = conn.execute("SELECT content FROM memories ORDER BY rowid").fetchall()
    assert rows
    for i, row in enumerate(rows, 1):
        prefix, body = row[0].split("] ", 1)
        assert body.strip() and prefix == f"[user {i}/{len(rows)}"


def test_list_jsonl_exports_all_identity_fields(conn, cfg, capsys):
    add(conn, cfg, "exchange", turn_id="turn", session_id="session", embed=False)
    memory.cmd_list(fmt="jsonl")
    output = capsys.readouterr()
    record = json.loads(output.out)
    assert set(record) == {"id", "timestamp", "agent_name", "content", "session_id", "turn_id", "owner_id", "local_id"}
    assert record["session_id"] == "session" and record["turn_id"] == "turn"
    assert record["owner_id"] == cfg["owner_id"] and record["local_id"] == cfg["local_id"]
    assert output.err == "Total: 1 records\n"


def test_reply_secret_is_reported_without_logging_secret(conn, capsys, monkeypatch):
    hook(PROMPT, "ordinary prompt")
    raw = json.dumps({"session_id": "chat", "turn_id": "turn", "last_assistant_message": "password=ActualLongValue123"})
    monkeypatch.setattr(codex_entry._sys, "stdin", io.StringIO(raw))
    assert codex_entry.stop_main() == 0
    output = capsys.readouterr()
    assert "excluded" in json.loads(output.out)["systemMessage"]
    assert "ActualLongValue123" not in output.out + output.err + Path(memory.AUDIT_LOG).read_text(encoding="utf-8")
    assert db.count_memories(conn) == 1


@pytest.mark.parametrize("outcome", ["ok", "offline", "wrong_root", "error"])
def test_connected_manual_buffer_uses_verified_target(outcome, tmp_path, monkeypatch, capsys):
    root = str(tmp_path / "remote")
    cfg = dict(memory.get_config(), connect_server_port=19520, connect_server_root=root)
    Path(memory.CONFIG_FILE).write_text(json.dumps(cfg), encoding="utf-8")
    memory._load_config()
    monkeypatch.setenv("N3MC_FREE_CODEX_SESSION_ID", "cli-session")
    monkeypatch.setattr(memory, "_get_health", lambda port: None if outcome == "offline" else
                        {"root": root if outcome != "wrong_root" else str(tmp_path)})
    requests = []
    def post(path, body, *, port):
        requests.append(path)
        assert path == "/buffer" and port == 19520
        assert body["session_id"] == "cli-session" and body["content"] == "a fact"
        return {"status": "ok" if outcome == "ok" else "error"}
    monkeypatch.setattr(memory, "_post", post)
    assert memory.cmd_buffer("a fact") == (0 if outcome == "ok" else 1)
    assert requests == (["/buffer"] if outcome in ("ok", "error") else [])
    assert not Path(memory.DB_PATH).exists()
    assert memory.cmd_repair() == memory.cmd_reembed() == 1
    assert requests == (["/buffer"] if outcome in ("ok", "error") else [])

@pytest.mark.parametrize("fields", [
    {"prompt": '{"password": "SyntheticValue123"}'},
    {"metadata": {"access_token": "SyntheticValue123"}},
    {"prompt": "api_key=`SyntheticValue123`"},
])
def test_structured_credentials_exclude_whole_turn(conn, fields, monkeypatch):
    monkeypatch.setattr(memory, "_search_text", lambda *a, **kw: pytest.fail("excluded prompt searched"))
    assert "excluded" in hook(PROMPT, fields.get("prompt", "hello"),
                              **{k: v for k, v in fields.items() if k != "prompt"})["systemMessage"]
    assert "excluded" in hook(STOP, "ordinary reply")["systemMessage"]
    assert not Path(memory.AUDIT_LOG).exists() and db.count_memories(conn) == 0


def test_repair_missing_bigram_after_migration(conn, cfg):
    add(conn, cfg, "盛岡", embed=True)
    memory._repair(conn, cfg)
    conn.execute("DELETE FROM memories_fts_bi")
    conn.commit()
    assert not db.search_fts_bigram(conn, "盛岡")
    assert memory._repair(conn, cfg, max_records=1) == 1
    assert db.search_fts_bigram(conn, "盛岡")


def test_bigram_backfill_respects_limit(conn, cfg):
    for name in ("盛岡", "花巻", "遠野"):
        add(conn, cfg, name, embed=True)
    memory._repair(conn, cfg)
    conn.execute("DELETE FROM memories_fts_bi")
    db.delete_meta(conn, "fts_bigram")
    conn.commit()
    memory._repair(conn, cfg, max_records=1)
    assert conn.execute("SELECT COUNT(*) FROM memories_fts_bi").fetchone()[0] == 1
    assert db.get_meta(conn, "fts_bigram") is None
    memory._repair(conn, cfg)
    assert db.get_meta(conn, "fts_bigram") == "1"


@pytest.mark.parametrize("present", [True, False])
def test_thread_jsonl_has_only_records(conn, cfg, capsys, present):
    if present:
        add(conn, cfg, "記録", turn_id="target", embed=False)
    memory.main(["--recall-thread", "target", "--format", "jsonl"])
    output = capsys.readouterr()
    assert [json.loads(line)["content"] for line in output.out.splitlines()] == (["記録"] if present else [])
    assert f"Total: {int(present)} records" in output.err
