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
    assert hook(PROMPT, prompt) is None
    assert hook(STOP, "I will respect the request") is None
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


@pytest.mark.parametrize("state", ["connected", "wrong_root", "offline", "half_config"])
def test_connected_search_never_writes_to_target_and_uses_local_audit(state, tmp_path, monkeypatch):
    root = str(tmp_path / "original")
    cfg = dict(memory.get_config(), connect_server_port=19520,
               connect_server_root=None if state == "half_config" else root)
    Path(memory.CONFIG_FILE).write_text(json.dumps(cfg), encoding="utf-8")
    memory._load_config()
    health = {"root": root if state == "connected" else str(tmp_path / "wrong"), "code_version": "another build"}
    calls = []
    def get_health(port):
        calls.append(("health", port))
        return None if state == "offline" else health

    def post(path, body, *, port):
        calls.append((path, port))
        assert path == "/search" and body == {"query": "question", "session_id": "chat"}
        return {"results": [], "pairs": {}, "pairs_omitted": {}}

    def use_server():
        assert state == "half_config"
        return False

    monkeypatch.setattr(memory, "_get_health", get_health)
    monkeypatch.setattr(memory, "_post", post)
    monkeypatch.setattr(memory, "_use_server", use_server)
    result = hook(PROMPT, "question")
    assert hook(STOP, "reply") is None
    expected = "No relevant memories" if state == "connected" else "memory search unavailable"
    assert expected in result["hookSpecificOutput"]["additionalContext"]
    events = Path(memory.AUDIT_LOG).read_text(encoding="utf-8").splitlines()
    assert len(events) == 2
    if state == "half_config":
        assert Path(memory.DB_PATH).exists() and calls == []
    else:
        assert not Path(memory.DB_PATH).exists()
        assert calls == ([("health", 19520), ("/search", 19520)] if state == "connected" else [("health", 19520)])


def test_recall_neighbours_are_from_same_session(conn, cfg, capsys):
    for turn, session in (("prior", "same"), ("other-1", "different"), ("anchor", "same"),
                          ("other-2", "different"), ("after", "same"), ("alone", None)):
        add(conn, cfg, turn, turn_id=turn, session_id=session, embed=False)
    assert memory.cmd_recall_thread("anchor", before=1, after=1, fmt="jsonl") == 0
    lines = capsys.readouterr().out.splitlines()
    assert [json.loads(line)["turn_id"] for line in lines[:-1]] == ["prior", "anchor", "after"]
    assert memory.cmd_recall_thread("alone", fmt="jsonl") == 0
    lines = capsys.readouterr().out.splitlines()
    assert [json.loads(line)["turn_id"] for line in lines[:-1]] == ["alone"]


def test_fts_rules_replace_old_index_and_resume(conn, cfg):
    add(conn, cfg, "[user] 佐々木", embed=True)
    add(conn, cfg, "[claude] talks about [code omitted]", embed=True)
    conn.execute("UPDATE memories_fts SET content=(SELECT content FROM memories WHERE rowid=memories_fts.rowid)")
    conn.commit()
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


@pytest.mark.parametrize("prompt", ["この会話の保存はやめてください", "Please don’t save this reply"])
def test_explicit_privacy_variants(conn, monkeypatch, prompt, capsys):
    monkeypatch.setattr(memory, "_search_text", lambda *a, **k: pytest.fail("excluded prompt reached search"))
    assert hook(PROMPT, prompt) is None
    assert hook(STOP, "acknowledged") is None
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
