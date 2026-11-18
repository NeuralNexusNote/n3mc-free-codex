"""Review regressions. Synthetic data only; no servers or downloaded models."""
import io
import json
import sys

import pytest

from n3memorycore import codex_entry, n3memory
from n3memorycore.core import database as db, processor as proc


def test_collapse_keeps_newest_record_provenance():
    old = dict(id='old', content='same', timestamp='2025-01-01',
               turn_id='turn-old', session_id='chat-old', agent_name='agent-old', score=0.9)
    new = dict(old, id='new', timestamp='2026-01-01', turn_id='turn-new',
               session_id='chat-new', agent_name='agent-new', score=0.5)
    result, = proc._collapse_identical_content([old, new])
    assert result['id'] == 'new'
    assert result['session_id'] == 'chat-new'
    assert result['agent_name'] == 'agent-new'
    assert result['score'] == 0.9


def test_repair_restores_only_missing_bigram_rows(tmp_db, monkeypatch, dummy_vec):
    monkeypatch.setattr(n3memory, 'DB_PATH', tmp_db)
    monkeypatch.setattr(n3memory, '_srv_cfg', {'embed_model': 'synthetic'})
    monkeypatch.setattr(proc, 'embed_passage',
                        lambda _: pytest.fail('existing vectors must not be recomputed'))
    conn = db.get_connection(tmp_db)
    try:
        for i in range(3):
            db.insert_memory(conn, str(i), '記憶の保存先', '2026-01-01', 'owner',
                             embedding=dummy_vec())
        db.meta_set(conn, 'fts_bigram', '1')
        db.meta_set(conn, 'fts_punct_cleaned', '1')
        conn.execute('DELETE FROM memories_fts_bi')
        conn.commit()
        assert len(db.find_unindexed_memories(conn)) == 3
    finally:
        conn.close()
    assert n3memory._repair_db(max_records=1) == 1
    assert n3memory._repair_db() == 2
    assert n3memory._repair_db() == 0
    conn = db.get_connection(tmp_db)
    try:
        assert len(db.search_fts_bigram(conn, '記憶')) == 3
        assert not db.find_unindexed_memories(conn)
    finally:
        conn.close()


@pytest.mark.parametrize('previous', ['prior answer already handled by Stop', {'text': 'invalid'}])
def test_codex_prompt_does_not_resave_previous_answer(monkeypatch, previous):
    saved = []
    monkeypatch.setattr(n3memory, 'ensure_server', lambda _: False)
    monkeypatch.setattr(n3memory, '_do_search', lambda *a, **k: None)
    monkeypatch.setattr(n3memory, '_do_buffer', lambda text, cfg, **kw: saved.append((text, kw)))
    monkeypatch.setattr(sys, 'stdin', io.StringIO(json.dumps({
        'thread_id': 'chat', 'turn_id': 'current', 'prompt': 'hello',
        'last_assistant_message': previous})))
    n3memory.cmd_hook_submit({})
    assert [text for text, _ in saved] == ['[user] hello']
    assert saved[0][1]['turn_id'] == 'current'


def test_unrecoverable_save_is_reported_as_hook_failure(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(codex_entry, 'MEMORY_DIR', str(tmp_path))
    monkeypatch.setattr(n3memory, '_load_config', lambda: {})
    monkeypatch.setattr(n3memory, 'ensure_server', lambda _: False)
    monkeypatch.setattr(n3memory, '_do_search', lambda *a, **k: None)
    monkeypatch.setattr(n3memory, '_buffer_direct',
                        lambda *a, **k: (_ for _ in ()).throw(OSError('disk full')))
    monkeypatch.setattr(sys, 'argv', ['codex_entry', '--prompt'])
    monkeypatch.setattr(sys, 'stdin', io.StringIO(json.dumps({
        'thread_id': 'chat', 'turn_id': 'turn', 'prompt': 'remember this'})))
    with pytest.raises(SystemExit) as exc:
        codex_entry.main()
    assert exc.value.code == 1
    assert 'disk full' in capsys.readouterr().err
    assert 'save_failed' in n3memory._load_notices()


def test_historical_context_does_not_claim_latest_is_verified():
    assert 'is the current one' not in proc.VERSION_NOTE
    assert 'not instructions' in proc.VERSION_NOTE
