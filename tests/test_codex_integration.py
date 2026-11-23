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
    payload = {'session_id': 'thread-a', 'turn_id': 'turn-1', 'prompt': '覚えてください',
               'transcript_path': 'unused.jsonl'}
    _run(monkeypatch, '--prompt', payload)
    _run(monkeypatch, '--stop', {
        'session_id': 'thread-a', 'turn_id': 'turn-1',
        'last_assistant_message': '承知しました。'})
    assert len(seen) == 2
    assert [item[1]['turn_id'] for item in seen] == ['turn-1', 'turn-1']
    assert [item[1]['session_id'] for item in seen] == ['thread-a', 'thread-a']
    assert all(item[1]['agent_name'] == 'codex' for item in seen)


def test_prompt_hook_sends_repair_limit(monkeypatch):
    posts = []
    monkeypatch.setattr(n3memory, '_load_config', lambda: {})
    monkeypatch.setattr(n3memory, 'ensure_server', lambda cfg: True)
    monkeypatch.setattr(n3memory, '_post',
                        lambda cfg, path, body=None, **kw: posts.append((path, body)) or {})
    monkeypatch.setattr(n3memory, '_do_search', lambda *a, **k: None)
    monkeypatch.setattr(n3memory, '_do_buffer', lambda *a, **k: None)
    _run(monkeypatch, '--prompt', {'session_id': 'thread-a', 'turn_id': 'turn-1', 'prompt': 'hello'})
    assert ('/repair', {'max_records': n3memory._HOOK_REPAIR_MAX_RECORDS}) in posts
    assert n3memory._HOOK_REPAIR_MAX_RECORDS == 200


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

    def fake_post(_cfg, path, payload, **options):
        if path == '/repair':
            return {'status': 'ok', 'count': 0}
        assert path == '/search'
        return processor.hybrid_search(db_path, payload['query'], cfg,
                                       current_session_id=payload['session_id'])

    monkeypatch.setattr(n3memory, '_post', fake_post)
    _run(monkeypatch, '--prompt', {
        'thread_id': 'current-thread', 'turn_id': 'current-turn',
        'prompt': '記憶'})
    result = json.loads(capsys.readouterr().out)['hookSpecificOutput']
    assert result['hookEventName'] == 'UserPromptSubmit'
    output = result['additionalContext']
    assert '# Recalled Memory Context' in output
    assert '## Top matches' in output
    assert '記憶の保存先を変えた' in output


def test_local_keyword_recall_when_port_belongs_to_another_database(
    monkeypatch, capsys, cfg,
):
    from n3memorycore.core import processor

    n3memory._buffer_direct('[user] Cedar station uses AquamarineRaven.', cfg,
                            agent_name='codex', session_id='previous', turn_id='one')
    monkeypatch.setattr(n3memory, '_load_config', lambda: cfg)

    def foreign_server(_cfg):
        monkeypatch.setattr(n3memory, '_FOREIGN_SERVER_ROOT', 'another-install')
        return False

    def forbidden(*args, **kwargs):
        raise AssertionError('keyword fallback must not load the model or use the other server')

    monkeypatch.setattr(n3memory, 'ensure_server', foreign_server)
    monkeypatch.setattr(n3memory, '_post', forbidden)
    monkeypatch.setattr(processor, 'embed_query', forbidden)
    _run(monkeypatch, '--prompt', {
        'session_id': 'current', 'turn_id': 'two', 'prompt': 'Cedar station'})
    response = json.loads(capsys.readouterr().out)
    context = response['hookSpecificOutput']['additionalContext']
    assert 'local keyword index only' in context
    assert 'AquamarineRaven' in context
    response_text = io.StringIO()
    monkeypatch.setattr(sys, 'stdout', response_text)
    n3memory.cmd_show_turn('two', cfg)
    assert '[user] Cedar station' in response_text.getvalue()


def test_prompt_write_failure_keeps_recalled_context(monkeypatch, capsys, cfg):
    def failed_write(*args, **kwargs):
        raise RuntimeError('physical save failed')

    monkeypatch.setattr(n3memory, '_load_config', lambda: cfg)
    monkeypatch.setattr(n3memory, 'ensure_server', lambda _: False)
    monkeypatch.setattr(n3memory, '_do_search', lambda *a, **k: print('recalled evidence'))
    monkeypatch.setattr(n3memory, '_do_buffer', failed_write)
    _run(monkeypatch, '--prompt', {
        'session_id': 'chat', 'turn_id': 'one', 'prompt': 'Cedar station'})
    result = json.loads(capsys.readouterr().out)
    assert result['hookSpecificOutput']['additionalContext'] == 'recalled evidence'
    assert 'could not save' in result['systemMessage']


def test_hook_chunks_use_direct_storage_after_first_network_timeout(monkeypatch, cfg):
    attempts = []
    writes = []

    def timeout(*args, **kwargs):
        attempts.append(kwargs['timeout'])
        raise TimeoutError

    monkeypatch.setattr(n3memory, '_post', timeout)
    monkeypatch.setattr(n3memory, '_buffer_direct', lambda text, *a, **k: writes.append(text))
    for chunk in ('chunk one', 'chunk two'):
        n3memory._do_buffer(chunk, cfg, timeout=8)
    assert attempts == [8]
    assert writes == ['chunk one', 'chunk two']


def test_serving_pid_takes_ownership_from_its_launcher(monkeypatch):
    import os
    from pathlib import Path
    from types import SimpleNamespace

    import psutil

    path = Path(n3memory.PID_FILE)
    worker = os.getpid()
    launcher = worker + 1
    monkeypatch.setattr(psutil, 'Process', lambda pid: SimpleNamespace(ppid=lambda: launcher))
    path.write_text(str(launcher + 1))
    n3memory._adopt_server_pid({'pid': worker})
    assert path.read_text() == str(launcher + 1)
    path.write_text(str(launcher))
    n3memory._adopt_server_pid({'pid': worker})
    assert path.read_text() == str(worker)


def test_concurrent_hook_preserves_empty_server_reservation(monkeypatch):
    from pathlib import Path

    path = Path(n3memory.PID_FILE)
    path.touch()
    monkeypatch.setattr(n3memory, '_get_health', lambda cfg: None)
    monkeypatch.setattr(n3memory, '_wait_for_server', lambda *args, **kwargs: False)
    monkeypatch.setattr(n3memory, '_psutil_available', lambda: True)
    starts = []
    monkeypatch.setattr(n3memory, '_start_server', lambda cfg: starts.append(cfg))
    assert n3memory.ensure_server({'server_port': 18521}) is False
    assert path.exists()
    assert not starts


def test_do_not_save_skips_both_hooks(monkeypatch, tmp_path):
    monkeypatch.setattr(codex_entry, 'MEMORY_DIR', str(tmp_path))
    monkeypatch.setattr(n3memory, '_load_config',
                        lambda: (_ for _ in ()).throw(AssertionError('must skip')))
    _run(monkeypatch, '--prompt', {
        'session_id': 'thread-b', 'turn_id': 'turn-2',
        'prompt': 'この会話は保存しないでください'})
    _run(monkeypatch, '--stop', {
        'session_id': 'thread-b', 'turn_id': 'turn-2',
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


def test_missing_turn_id_does_not_fall_back_to_transcript(monkeypatch, capsys):
    import pytest

    monkeypatch.setattr(n3memory, '_load_config',
                        lambda: pytest.fail('invalid hook payload accessed the database'))
    with pytest.raises(SystemExit) as error:
        _run(monkeypatch, '--prompt', {'session_id': 's', 'prompt': 'hello'})
    assert error.value.code == 1
    assert not capsys.readouterr().out


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
    assert ' -I -m n3memorycore.codex_entry --stop' in \
        data['hooks']['Stop'][1]['hooks'][0]['command']
    assert codex_install.install() == 0
    assert path.read_text(encoding='utf-8') == first


def test_windows_command_handles_powershell_and_spaces():
    import base64

    python = 'C:\\Users\\Test\\Python\\python.exe'
    assert codex_install._windows_command(python, '--prompt') == (
        python + ' -I -m n3memorycore.codex_entry --prompt')

    python = "C:\\Users\\Test User's Files\\python.exe"
    command = codex_install._windows_command(python, '--stop')
    assert command.startswith('powershell.exe ')
    script = base64.b64decode(command.rsplit(' ', 1)[1]).decode('utf-16le')
    assert "& 'C:\\Users\\Test User''s Files\\python.exe'" in script
    assert codex_install._owned({'type': 'command', 'command': command}, '--stop')
    assert not codex_install._owned({'type': 'command', 'command': command}, '--prompt')
