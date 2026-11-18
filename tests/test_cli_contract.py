"""CLI output contracts that must hold with a real isolated SQLite DB."""
import json
from datetime import datetime, timezone

from n3memorycore import n3memory
from n3memorycore.core.database import get_connection, init_db, insert_memory


def _database(tmp_path, monkeypatch, records):
    path = tmp_path / 'memory.db'
    monkeypatch.setattr(n3memory, 'DB_PATH', str(path))
    conn = get_connection(str(path))
    init_db(conn)
    for idx, (turn, session, content) in enumerate(records):
        insert_memory(conn, str(idx), content,
                      datetime.now(timezone.utc).isoformat(), 'owner',
                      session_id=session, turn_id=turn)
    conn.close()


def test_list_jsonl_has_only_json_records(tmp_path, monkeypatch, capsys):
    _database(tmp_path, monkeypatch, [('a1', 'a', '[user] first')])
    n3memory.cmd_list({}, fmt='jsonl')
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])['content'] == '[user] first'


def test_list_empty_jsonl_has_no_non_json_footer(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(n3memory, 'DB_PATH', str(tmp_path / 'missing.db'))
    n3memory.cmd_list({}, fmt='jsonl')
    assert capsys.readouterr().out == ''


def test_recall_thread_stays_in_its_chat_and_jsonl_is_parseable(
    tmp_path, monkeypatch, capsys
):
    _database(tmp_path, monkeypatch, [
        ('a1', 'chat-a', '[user] before'),
        ('b1', 'chat-b', '[user] unrelated before'),
        ('a2', 'chat-a', '[user] target'),
        ('b2', 'chat-b', '[user] unrelated after'),
        ('a3', 'chat-a', '[user] after'),
    ])
    n3memory.cmd_recall_thread('a2', {}, fmt='jsonl')
    records = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [record['turn_id'] for record in records] == ['a1', 'a2', 'a3']


def test_show_turn_keeps_full_multiline_content_in_role_order(
    tmp_path, monkeypatch, capsys
):
    _database(tmp_path, monkeypatch, [
        ('same', 'chat-a', '[claude] full answer\nsecond line'),
        ('same', 'chat-a', '[user] full question'),
    ])
    n3memory.cmd_show_turn('same', {})
    output = capsys.readouterr().out
    assert output.index('[user] full question') < output.index('[claude] full answer')
    assert '[claude] full answer\nsecond line' in output
    assert output.rstrip().endswith('Total: 2 records')


def test_tsv_content_keeps_four_columns_with_tabs(
    tmp_path, monkeypatch, capsys
):
    _database(tmp_path, monkeypatch, [('a1', 'chat-a', '[user] one\ttwo\nthree')])
    n3memory.cmd_list({}, fmt='tsv')
    row, total = capsys.readouterr().out.splitlines()
    assert len(row.split('\t')) == 4
    assert row.endswith('[user] one two three')
    assert total == 'Total: 1 records'


def test_buffer_unknown_server_response_falls_back_to_direct_write(monkeypatch):
    saved = []
    monkeypatch.setattr(n3memory, '_FOREIGN_SERVER_ROOT', None)
    monkeypatch.setattr(n3memory, '_NO_SERVER_REASON', None)
    monkeypatch.setattr(n3memory, '_post', lambda *_: {'status': 'unexpected'})
    monkeypatch.setattr(n3memory, '_buffer_direct',
                        lambda text, cfg, **kw: saved.append(text))
    n3memory._do_buffer('remember this', {'server_port': 18521})
    assert saved == ['remember this']


def test_repair_error_response_is_reported(monkeypatch, capsys):
    monkeypatch.setattr(n3memory, 'ensure_server', lambda _: True)
    monkeypatch.setattr(n3memory, '_NO_SERVER_REASON', None)
    monkeypatch.setattr(n3memory, '_post',
                        lambda *_: {'status': 'error', 'message': 'repair failed'})
    n3memory.cmd_repair({'server_port': 18521})
    assert 'Repair failed: repair failed' in capsys.readouterr().err
