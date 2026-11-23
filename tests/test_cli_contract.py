"""CLI output contracts that must hold with a real isolated SQLite DB."""
import json
from datetime import datetime, timezone

from n3memorycore import n3memory
from n3memorycore.core.database import get_connection, init_db, insert_memory, meta_get, meta_set


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
    conn = get_connection(n3memory.DB_PATH)
    with conn:
        conn.execute("UPDATE memories SET agent_name=?", ("custom\tagent\nname",))
    conn.close()
    n3memory.cmd_list({}, fmt='tsv')
    row, total = capsys.readouterr().out.splitlines()
    assert len(row.split('\t')) == 4
    assert row.split('\t')[2] == 'custom agent name'
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
    assert n3memory.cmd_repair({'server_port': 18521}) == 1
    assert 'Repair failed: repair failed' in capsys.readouterr().err


def test_configured_session_is_forwarded_by_manual_buffer_and_search(monkeypatch):
    monkeypatch.setenv('N3MC_SESSION_ID', 'manual-chat')
    monkeypatch.setattr(n3memory, 'ensure_server', lambda _: True)
    requests = []

    def post(cfg, endpoint, payload):
        requests.append((endpoint, payload['session_id']))
        return {'status': 'ok'}

    monkeypatch.setattr(n3memory, '_post', post)
    config = {'server_port': 18520}
    n3memory.cmd_buffer('keep this', config)
    n3memory.cmd_search('keep', config)
    assert requests == [('/buffer', 'manual-chat'), ('/search', 'manual-chat')]


def test_recall_excludes_turns_that_overlap_the_target(tmp_path, monkeypatch, capsys):
    _database(tmp_path, monkeypatch, [
        ('before', 'chat-a', '[user] earlier complete turn'),
        ('overlap', 'chat-a', '[user] starts outside target'),
        ('target', 'chat-a', '[user] question'),
        ('target', 'chat-a', '[claude] answer'),
        ('overlap', 'chat-a', '[claude] ends outside target'),
        ('after', 'chat-a', '[user] later complete turn'),
    ])
    n3memory.cmd_recall_thread('target', {}, before=1, after=1, fmt='jsonl')
    records = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [record['turn_id'] for record in records] == ['before', 'target', 'target', 'after']


def test_limited_fts_migration_resumes_from_committed_cursor(tmp_path, monkeypatch):
    _database(tmp_path, monkeypatch, [('a', 's', 'alpha'), ('b', 's', 'beta'), ('c', 's', 'gamma')])
    conn = get_connection(n3memory.DB_PATH)
    try:
        with conn:
            conn.execute("UPDATE memories_fts SET content=content || '!'")
        for cursor in (1, 2):
            assert n3memory._repair_db(max_records=1) == 1
            assert meta_get(conn, 'fts_punct_cursor') == str(cursor)
            assert meta_get(conn, 'fts_punct_cleaned') is None
        assert n3memory._repair_db(max_records=1) == 1
        assert meta_get(conn, 'fts_punct_cursor') is None
        assert meta_get(conn, 'fts_punct_cleaned') == '1'
        assert '!' not in ''.join(row[0] for row in conn.execute('SELECT content FROM memories_fts'))
    finally:
        conn.close()


def test_repair_rechecks_indexes_filled_during_embedding(tmp_path, monkeypatch):
    from n3memorycore.core import processor

    _database(tmp_path, monkeypatch, [('turn', 'chat', 'keyword')])
    conn = get_connection(n3memory.DB_PATH)
    try:
        with conn:
            meta_set(conn, 'fts_bigram', '1')
            conn.execute('DELETE FROM memories_fts')
            conn.execute('DELETE FROM memories_fts_bi')

        def already_repaired(text):
            with conn:
                conn.execute("INSERT INTO memories_fts(rowid, content) VALUES (1, 'keyword')")
                conn.execute("INSERT INTO memories_fts_bi(rowid, content) VALUES (1, 'keyword')")
            return [0.0] * 768

        monkeypatch.setattr(processor, 'embed_passage', already_repaired)
        assert n3memory._repair_db(max_records=1) == 1
        assert conn.execute('SELECT count(*) FROM memories_fts').fetchone()[0] == 1
        assert conn.execute('SELECT count(*) FROM memories_fts_bi').fetchone()[0] == 1
    finally:
        conn.close()
