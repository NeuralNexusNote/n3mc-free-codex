import io
import json
import sys
from datetime import datetime, timezone

from n3memorycore import codex_entry, codex_install, n3memory


def _run(monkeypatch, flag, payload):
    monkeypatch.setattr(sys, 'argv', ['codex_entry', flag])
    monkeypatch.setattr(sys, 'stdin', io.StringIO(json.dumps(payload)))
    codex_entry.main()


def test_codex_turn_pairing(monkeypatch):
    seen = []
    monkeypatch.setattr(n3memory, '_load_config', lambda: {})
    monkeypatch.setattr(n3memory, 'ensure_server', lambda cfg: False)
    monkeypatch.setattr(n3memory, '_do_search', lambda *a, **k: None)
    monkeypatch.setattr(n3memory, '_do_buffer',
                        lambda text, cfg, **kw: seen.append((text, kw)))
    monkeypatch.setattr(n3memory, '_housekeeping', lambda: None)
    payload = {'thread_id': 'thread-a', 'turn_id': 'turn-1', 'prompt': '覚えてください'}
    _run(monkeypatch, '--prompt', payload)
    _run(monkeypatch, '--stop', {
        'thread_id': 'thread-a', 'turn_id': 'turn-1',
        'last_assistant_message': '承知しました。'})
    assert len(seen) == 2
    assert [item[1]['turn_id'] for item in seen] == ['turn-1', 'turn-1']
    assert [item[1]['session_id'] for item in seen] == ['thread-a', 'thread-a']
    assert all(item[1]['agent_name'] == 'codex' for item in seen)


def test_keyword_hit_reaches_codex_stdout_without_embeddings(
    monkeypatch, tmp_path, capsys
):
    from n3memorycore.core import processor
    from n3memorycore.core.database import get_connection, init_db, insert_memory

    db_path = str(tmp_path / 'memory.db')
    conn = get_connection(db_path)
    init_db(conn)
    insert_memory(conn, 'prior-turn', '[user] 記憶の保存先を変えた',
                  datetime.now(timezone.utc).isoformat(), 'owner',
                  session_id='older-thread', turn_id='prior-turn')
    conn.close()

    cfg = dict(n3memory._DEFAULT_CONFIG)
    cfg['server_port'] = 18521
    monkeypatch.setattr(n3memory, '_load_config', lambda: cfg)
    monkeypatch.setattr(n3memory, 'ensure_server', lambda _: True)
    monkeypatch.setattr(n3memory, '_do_buffer', lambda *a, **k: None)
    monkeypatch.setattr(processor, 'embed_query',
                        lambda _: (_ for _ in ()).throw(RuntimeError('offline')))

    def fake_post(_cfg, path, payload):
        if path == '/repair':
            return {'status': 'ok', 'count': 0}
        assert path == '/search'
        return processor.hybrid_search(db_path, payload['query'], cfg,
                                       current_session_id=payload['session_id'])

    monkeypatch.setattr(n3memory, '_post', fake_post)
    _run(monkeypatch, '--prompt', {
        'thread_id': 'current-thread', 'turn_id': 'current-turn',
        'prompt': '記憶'})
    output = capsys.readouterr().out
    assert '# Recalled Memory Context' in output
    assert '## Top matches' in output
    assert '記憶の保存先を変えた' in output


def test_do_not_save_skips_both_hooks(monkeypatch, tmp_path):
    monkeypatch.setattr(codex_entry, 'MEMORY_DIR', str(tmp_path))
    monkeypatch.setattr(n3memory, '_load_config',
                        lambda: (_ for _ in ()).throw(AssertionError('must skip')))
    _run(monkeypatch, '--prompt', {
        'thread_id': 'thread-b', 'turn_id': 'turn-2',
        'prompt': 'この会話は保存しないでください'})
    _run(monkeypatch, '--stop', {
        'thread_id': 'thread-b', 'turn_id': 'turn-2',
        'last_assistant_message': '了解しました。'})


def test_credential_skips_both_hooks(monkeypatch, tmp_path):
    monkeypatch.setattr(codex_entry, 'MEMORY_DIR', str(tmp_path))
    monkeypatch.setattr(n3memory, '_load_config',
                        lambda: (_ for _ in ()).throw(AssertionError('must skip')))
    _run(monkeypatch, '--prompt', {
        'thread_id': 'thread-c', 'turn_id': 'turn-3',
        'prompt': 'api_key=abcdefghijklmnop'})
    _run(monkeypatch, '--stop', {
        'thread_id': 'thread-c', 'turn_id': 'turn-3',
        'last_assistant_message': '確認しました。'})


def test_positive_save_request_is_not_skipped():
    assert not codex_entry._NO_SAVE.search('この設定を保存をお願いします')


def test_install_preserves_other_hooks_and_is_idempotent(monkeypatch, tmp_path):
    path = tmp_path / 'hooks.json'
    path.write_text(json.dumps({'hooks': {'Stop': [
        {'hooks': [{'type': 'command', 'command': 'other-program'}]}
    ]}, 'custom': True}), encoding='utf-8')
    monkeypatch.setenv('N3MC_CODEX_HOOKS_PATH', str(path))
    assert codex_install.install() == 0
    first = path.read_text(encoding='utf-8')
    data = json.loads(first)
    assert data['custom'] is True
    assert data['hooks']['Stop'][0]['hooks'][0]['command'] == 'other-program'
    assert codex_install.install() == 0
    assert path.read_text(encoding='utf-8') == first
