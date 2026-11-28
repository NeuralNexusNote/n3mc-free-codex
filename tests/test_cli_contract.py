"""Regressions at the Free Codex CLI boundary."""
import io
import json
import sqlite3
from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from n3memorycore_free_codex import n3memory as memory


@pytest.mark.parametrize(("raw", "expected"), [
    ("0001-01-01T00:00:00+09:00", "0001-01-01T00:00:00+00:00"),
    ("9999-12-31T23:59:59-09:00", "9999-12-31T23:59:59.999999+00:00"),
])
def test_out_of_range_utc_bounds_are_clamped(raw, expected):
    assert memory._parse_time_bound(raw) == expected


def test_platform_local_time_failure_uses_utc(monkeypatch):
    class WindowsDate(datetime):
        def astimezone(self, tz=None):
            if tz is None:
                raise OSError("unsupported local date")
            return super().astimezone(tz)

    monkeypatch.setattr(memory, "datetime", WindowsDate)
    assert memory._parse_time_bound("1969-01-01") == "1969-01-01T00:00:00+00:00"
    assert memory._parse_time_bound("9999-12-31", upper=True) == "9999-12-31T23:59:59.999999+00:00"


@pytest.mark.parametrize(("bounds", "error"), [
    (["--since", ""], "--since: cannot read"),
    (["--since", "2026-03-02Z", "--until", "2026-03-01Z"], "--since: cannot read"),
    (["--since", "2026-03-02", "--until", "2026-03-01"], "--since is later than --until"),
])
def test_search_and_list_validate_explicit_bounds(bounds, error, capsys):
    for command in (["--search", "example"], ["--list"]):
        assert memory.main([*command, *bounds]) == 2
        output = capsys.readouterr()
        assert not output.out and error in output.err
    fields = {key[2:]: value for key, value in zip(bounds[::2], bounds[1::2])}
    client = TestClient(memory.create_app(), base_url="http://127.0.0.1:18526")
    answer = client.post("/search", json={"query": "example", **fields})
    assert answer.status_code == 400 and error in answer.json()["detail"]


@pytest.mark.parametrize("args", [
    ["--init", "--list"],
    ["--stop", "--since", "2026-11-25"],
    ["--show-turn", "turn", "--format", "jsonl"],
    ["--search", "term", "--agent-id", "writer"],
    ["--list", "--before", "0"],
])
def test_cli_rejects_arguments_that_would_previously_be_ignored(args):
    with pytest.raises(SystemExit) as error:
        memory.main(args)
    assert error.value.code == 2
    assert not Path(memory.DB_PATH).exists()


def test_legacy_list_and_turn_reads_do_not_migrate_the_database(capsys):
    with sqlite3.connect(memory.DB_PATH) as db:
        db.execute("CREATE TABLE memories (id TEXT PRIMARY KEY, content TEXT, timestamp TEXT, owner_id TEXT)")
        db.execute("INSERT INTO memories VALUES ('r1', 'older memory', '2026-11-25T00:00:00+00:00', 'owner')")

    path = Path(memory.DB_PATH)
    before = path.read_bytes()
    assert memory.main(["--list", "--format", "jsonl"]) == 0
    output = capsys.readouterr()
    row = output.out.strip()
    footer = output.err.strip()
    assert json.loads(row)["agent_name"] is None and footer == "Total: 1 records"
    for cmd in ("--recall-thread", "--show-turn"):
        assert memory.main([cmd, "unknown"]) == 0
        assert capsys.readouterr().out == "Total: 0 records\n"
    assert path.read_bytes() == before
    assert not Path(memory.CONFIG_FILE).exists()


def test_absent_database_has_consistent_empty_output(capsys):
    for cli in (["--list"], ["--show-turn", "t"], ["--recall-thread", "t"]):
        assert memory.main(cli) == 0
        output = capsys.readouterr()
        assert output.out == "Total: 0 records\n" and "No DB found" in output.err
    assert not Path(memory.DB_PATH).exists()


def test_buffer_stdio_and_explicit_empty_agent_match_server_and_output(conn, monkeypatch, capsys):
    captured = {}
    monkeypatch.setattr(memory.sys, "stdin", io.StringIO("日本語\tbody\r\n"))
    monkeypatch.setattr(memory, "_use_server", lambda: True)
    monkeypatch.setenv("N3MC_FREE_CODEX_SESSION_ID", "caller")
    with TestClient(memory.create_app(), base_url="http://127.0.0.1:18526") as client:
        def post(path, body, **_):
            captured.update(body)
            return client.post(path, json=body).json()

        monkeypatch.setattr(memory, "_post", post)
        monkeypatch.setattr(memory, "embed_passage", lambda *args: [0.0] * 768)
        assert memory.main(["--buffer", "-", "--agent-id="]) == 0
    assert captured == {"content": "日本語\tbody\r\n", "agent_name": "", "session_id": "caller"}
    assert capsys.readouterr().out == "Saved 1 record.\n"
    assert memory.main(["--list"]) == 0
    assert capsys.readouterr().out.splitlines()[0].split("\t")[2] == ""


def test_buffer_rejects_invalid_utf8_without_saving(monkeypatch, capsys):
    monkeypatch.setattr(memory.sys, "stdin", io.TextIOWrapper(io.BytesIO(b"before\xffafter")))
    assert memory.main(["--buffer", "-"]) == 1
    output = capsys.readouterr()
    assert output.out == "" and "stdin must be valid UTF-8" in output.err
    assert not Path(memory.DB_PATH).exists()


def test_connected_buffer_keeps_explicit_empty_agent(monkeypatch, tmp_path, capsys):
    captured = {}
    target = (19520, str(tmp_path))
    monkeypatch.setattr(memory, "_connection_target", lambda *_: target)
    monkeypatch.setattr(memory, "_verified_target", lambda info: info == target)

    def post(path, body, *, port):
        assert path == "/buffer" and port == target[0]
        captured.update(body)
        return {"status": "ok", "count": 1}

    monkeypatch.setattr(memory, "_post", post)
    assert memory.main(["--buffer", "connected record", "--agent-id="]) == 0
    assert captured["agent_name"] == "" and capsys.readouterr().out == "Saved 1 record.\n"
    assert not Path(memory.DB_PATH).exists()


def test_recall_thread_accepts_limits_larger_than_a_sqlite_integer(conn, capsys):
    for i, (session, turn) in enumerate([("one", "previous"), ("two", "unrelated"),
                                         ("one", "anchor"), ("one", "following")]):
        conn.execute("INSERT INTO memories (id, content, timestamp, owner_id, session_id, turn_id) "
                     "VALUES (?, ?, '2026-11-28T00:00:00+00:00', 'owner', ?, ?)",
                     (f"row-{i}", turn, session, turn))
    conn.commit()
    large = str(1 << 63)
    assert memory.main(["--recall-thread", "anchor", "--before", large, "--after", large,
                        "--format", "jsonl"]) == 0
    output = capsys.readouterr()
    assert [json.loads(line)["turn_id"] for line in output.out.splitlines()] == ["previous", "anchor", "following"]
    assert output.err == "Total: 3 records\n"


@pytest.mark.skipif(not hasattr(sqlite3.Connection, "setlimit"), reason="setlimit requires Python 3.11")
def test_recall_thread_window_can_exceed_sqlite_variable_limit(conn, monkeypatch, capsys):
    for i in range(12):
        conn.execute("INSERT INTO memories (id, content, timestamp, owner_id, session_id, turn_id) "
                     "VALUES (?, 'record', '2026-11-28', 'owner', 'session', ?)", (str(i), str(i)))
    conn.commit()
    open_db = memory._read_db_if_exists

    def open_limited():
        reader = open_db()
        reader.setlimit(sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER, 8)
        return reader

    monkeypatch.setattr(memory, "_read_db_if_exists", open_limited)
    assert memory.main(["--recall-thread", "5", "--before", "20", "--after", "20",
                        "--format", "jsonl"]) == 0
    output = capsys.readouterr()
    assert [json.loads(row)["turn_id"] for row in output.out.splitlines()] == list(map(str, range(12)))
    assert output.err == "Total: 12 records\n"


@pytest.mark.parametrize("response", [{"status": "error"}, {"status": "ok", "count": -1}, {}])
def test_invalid_repair_response_is_a_cli_failure(monkeypatch, capsys, response):
    monkeypatch.setattr(memory, "_use_server", lambda: True)
    monkeypatch.setattr(memory, "_post", lambda *args, **kwargs: response)
    assert memory.main(["--repair"]) == 1
    output = capsys.readouterr()
    assert not output.out and "repair failed" in output.err


def test_server_uses_data_directory_from_outside_checkout(isolated, monkeypatch):
    monkeypatch.chdir(isolated)
    assert memory._server_cwd() == memory.HOME_DIR
    monkeypatch.chdir(Path(memory.__file__).resolve().parents[1])
    assert memory._server_cwd() == str(Path(memory.__file__).resolve().parents[1])


def test_duplicate_internal_server_leaves_active_pid_unchanged(monkeypatch, capsys):
    pid = Path(memory.PID_FILE)
    pid.write_text("54321", encoding="utf-8")
    monkeypatch.setattr(memory, "_get_health", lambda port: {"root": memory.HOME_DIR})
    assert memory.main(["--run-server"]) == 1
    assert "already listens" in capsys.readouterr().err
    assert pid.read_text(encoding="utf-8") == "54321"


def test_reembed_checks_dimensions_before_shutdown(conn, monkeypatch, capsys):
    monkeypatch.setattr(memory._processor, "get_model", lambda *args: object())
    monkeypatch.setattr(memory, "embed_passage", lambda *args: [0.0] * 384)

    def unexpected_health(*args, **kwargs):
        pytest.fail("Invalid probe must not affect the resident server")

    monkeypatch.setattr(memory, "_get_health", unexpected_health)
    assert memory.main(["--reembed"]) == 1
    assert "memories_vec has 768" in capsys.readouterr().err
    assert conn.execute("SELECT COUNT(*) FROM meta").fetchone()[0] == 0


def test_reembed_will_not_write_when_local_server_cannot_stop(conn, monkeypatch, capsys):
    monkeypatch.setattr(memory._processor, "get_model", lambda *args: object())
    monkeypatch.setattr(memory, "embed_passage", lambda *args: [0.0] * 768)
    monkeypatch.setattr(memory, "_get_health", lambda: {"root": memory.HOME_DIR})
    monkeypatch.setattr(memory, "_stop_stale_server", lambda *_: False)
    assert memory.main(["--reembed"]) == 1
    assert "could not stop" in capsys.readouterr().err
    assert conn.execute("SELECT COUNT(*) FROM meta").fetchone()[0] == 0


def test_reembed_reports_corrupt_resume_cursor_without_changing_index(conn, monkeypatch, capsys):
    model = memory.get_config()["embed_model"]
    memory.set_meta(conn, "reembed_model", model)
    memory.set_meta(conn, "reembed_cursor", "invalid")
    conn.commit()
    monkeypatch.setattr(memory._processor, "get_model", lambda *args: object())
    monkeypatch.setattr(memory, "embed_passage", lambda *args: [0.0] * 768)
    assert memory.main(["--reembed"]) == 1
    output = capsys.readouterr()
    assert not output.out and "invalid reembed_cursor" in output.err
    assert memory.get_meta(conn, "reembed_cursor") == "invalid"
    assert memory.get_meta(conn, "embed_model") is None
