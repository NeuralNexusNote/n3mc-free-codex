"""CPU-only retrieval and lifecycle tests. No production data or servers."""
import json
from pathlib import Path
import sqlite3
import sys
import types

import pytest

from n3memorycore import maintenance as maint, n3memory
from n3memorycore.core import database as db, processor as proc
from tests.test_regressions import unit, at_cos, cfg


def seed(path, turn='old', text='[claude] azure plan costs 980', vec=None, rid=None, owner='owner'):
    conn = db.get_connection(str(path))
    try:
        db.init_db(conn)
        db.insert_memory(conn, rid or turn, text, '2026-11-18T00:00:00+00:00', owner,
                         embedding=vec, turn_id=turn, session_id='chat-' + turn, agent_name='codex')
    finally:
        conn.close()


def rows(path, table='memories'):
    conn = db.get_connection(str(path))
    try:
        return [dict(r) for r in conn.execute(f'SELECT * FROM {table}')]
    finally:
        conn.close()


def test_model_loader_explicitly_selects_cpu(monkeypatch):
    seen = []
    fake = types.SimpleNamespace(SentenceTransformer=lambda *a, **kw: seen.append((a, kw)))
    monkeypatch.setitem(sys.modules, 'sentence_transformers', fake)
    proc._load_model('local-model')
    assert seen == [(('local-model',), {'device': 'cpu'})]


def test_old_schema_migrates_without_changing_original_data(tmp_path):
    path = tmp_path / 'legacy.db'
    conn = sqlite3.connect(path)
    conn.execute('CREATE TABLE memories(id TEXT PRIMARY KEY, content TEXT NOT NULL, timestamp TEXT NOT NULL, owner_id TEXT NOT NULL)')
    conn.execute("INSERT INTO memories VALUES ('a', '[user] remember', '2026-01-01', 'owner')")
    conn.commit()
    conn.close()
    conn = db.get_connection(str(path))
    try:
        db.init_db(conn)
        db.migrate_schema(conn)
        db.migrate_schema(conn)
        r = conn.execute('SELECT rowid, * FROM memories').fetchone()
        assert (r['rowid'], r['id'], r['content'], r['role'], r['source']) == (
            1, 'a', '[user] remember', 'user', 'unspecified')
        assert conn.execute('SELECT COUNT(*) FROM current_memories').fetchone()[0] == 1
    finally:
        conn.close()


def test_supersession_filters_before_limits_and_keeps_history(tmp_db, monkeypatch):
    seed(tmp_db, vec=unit(0))
    seed(tmp_db, turn='new', text='[claude] azure plan costs 1480', vec=at_cos(.9))
    preview = maint.change_turn(tmp_db, 'old', 'new')
    assert not preview['applied'] and not rows(tmp_db, 'turn_lifecycle')
    maint.change_turn(tmp_db, 'old', 'new', apply=True)
    conn = db.get_connection(tmp_db)
    try:
        assert [r['turn_id'] for r in db.search_vector(conn, unit(0), k=1)] == ['new']
        assert [r['turn_id'] for r in db.search_fts(conn, 'azure', limit=1)] == ['new']
        assert [r['turn_id'] for r in db.search_fts_bigram(conn, 'azure', limit=1)] == ['new']
        assert [r['turn_id'] for r in db.search_vector_with_filter(
            conn, unit(0), k=1, since='2020')] == ['new']
        assert db.get_memories_by_turn_id(conn, 'old')[0]['content'].endswith('980')
    finally:
        conn.close()
    monkeypatch.setattr(proc, 'embed_query', lambda _: unit(0))
    out = proc.hybrid_search(tmp_db, 'azure', cfg(min_results=3))
    assert {r['turn_id'] for r in out['results']} == {'new'}
    assert 'old' not in out['pairs']
    assert out['results'][0]['role'] == 'assistant'


@pytest.mark.parametrize('scenario', ['self', 'missing', 'other-owner', 'retired'])
def test_invalid_corrections_leave_database_unchanged(tmp_db, scenario):
    seed(tmp_db)
    seed(tmp_db, turn='new', owner='other' if scenario == 'other-owner' else 'owner')
    if scenario == 'retired':
        maint.change_turn(tmp_db, 'new', apply=True)
    before = rows(tmp_db, 'turn_lifecycle')
    replacement = {'self': 'old', 'missing': 'missing'}.get(scenario, 'new')
    with pytest.raises(ValueError):
        maint.change_turn(tmp_db, 'old', replacement, apply=True)
    assert rows(tmp_db, 'turn_lifecycle') == before


def test_correction_chain_rejects_cycles(tmp_db):
    for turn in ('a', 'b', 'c'):
        seed(tmp_db, turn=turn)
    maint.change_turn(tmp_db, 'a', 'b', apply=True)
    maint.change_turn(tmp_db, 'b', 'c', apply=True)
    with pytest.raises(ValueError):
        maint.change_turn(tmp_db, 'c', 'a', apply=True)
    assert len(rows(tmp_db)) == 3


def test_forget_is_atomic_and_blocks_hook_retry(tmp_db):
    seed(tmp_db, vec=unit(0))
    seed(tmp_db, rid='question', text='[user] azure?', vec=unit(0))
    assert maint.change_turn(tmp_db, 'old')['records'] == 2
    assert len(rows(tmp_db)) == 2
    maint.change_turn(tmp_db, 'old', apply=True)
    for table in ('memories', 'memories_vec', 'memories_fts', 'memories_fts_bi'):
        assert not rows(tmp_db, table)
    conn = db.get_connection(tmp_db)
    try:
        assert db.insert_memory_once(conn, 'retry-new-id', '[claude] regenerated answer',
                                     '2026-11-18', 'owner', turn_id='old') is None
    finally:
        conn.close()
    assert maint.change_turn(tmp_db, 'old', apply=True)['records'] == 0


def test_failed_forget_rolls_back_all_indexes(tmp_db):
    seed(tmp_db, vec=unit(0))
    conn = db.get_connection(tmp_db)
    conn.execute("CREATE TRIGGER reject_delete BEFORE DELETE ON memories BEGIN SELECT RAISE(ABORT, 'blocked'); END")
    conn.commit()
    conn.close()
    with pytest.raises(sqlite3.IntegrityError):
        maint.change_turn(tmp_db, 'old', apply=True)
    for table in ('memories', 'memories_vec', 'memories_fts', 'memories_fts_bi'):
        assert len(rows(tmp_db, table)) == 1
    assert not rows(tmp_db, 'turn_lifecycle')


def test_forget_during_repair_does_not_resurrect_index(tmp_db, monkeypatch):
    seed(tmp_db)
    monkeypatch.setattr(n3memory, 'DB_PATH', tmp_db)
    monkeypatch.setattr(n3memory, '_srv_cfg', {'embed_model': 'synthetic'})
    def embed(_):
        maint.change_turn(tmp_db, 'old', apply=True)
        return unit(0)
    monkeypatch.setattr(proc, 'embed_passage', embed)
    n3memory._repair_db()
    assert not rows(tmp_db, 'memories_vec')
    assert not rows(tmp_db)


def test_backup_restores_wal_metadata_and_search(tmp_db, tmp_path, monkeypatch):
    seed(tmp_db, vec=unit(0))
    seed(tmp_db, turn='new', text='[claude] azure costs 1480', vec=unit(0))
    maint.change_turn(tmp_db, 'old', 'new', apply=True)
    config = tmp_path / 'config.json'
    config.write_text('{"owner_id":"owner"}', encoding='utf-8')
    writer = db.get_connection(tmp_db)
    try:
        db.meta_set(writer, 'test_marker', 'committed-in-wal')
        writer.commit()
        backup = tmp_path / 'backup'
        assert maint.backup_database(tmp_db, config, backup)['records'] == 2
        restored = tmp_path / 'restored'
        assert maint.restore_database(backup, restored)['records'] == 2
    finally:
        writer.close()
    path = str(restored / '.memory' / 'n3memory.db')
    assert rows(path, 'turn_lifecycle') == rows(tmp_db, 'turn_lifecycle')
    conn = db.get_connection(path)
    try:
        assert db.meta_get(conn, 'test_marker') == 'committed-in-wal'
    finally:
        conn.close()
    monkeypatch.setattr(proc, 'embed_query', lambda _: unit(0))
    assert {r['turn_id'] for r in proc.hybrid_search(path, 'azure', cfg())['results']} == {'new'}
    with pytest.raises(FileExistsError):
        maint.restore_database(backup, restored)
    with pytest.raises(FileExistsError):
        maint.backup_database(tmp_db, config, backup)


def test_tampered_backup_is_rejected_before_creating_home(tmp_db, tmp_path):
    seed(tmp_db)
    config = tmp_path / 'config.json'
    config.write_text('{}')
    backup = tmp_path / 'backup'
    maint.backup_database(tmp_db, config, backup)
    (backup / 'config.json').write_text('{"tampered":true}')
    target = tmp_path / 'new-home'
    with pytest.raises(ValueError, match='checksum'):
        maint.restore_database(backup, target)
    assert not target.exists()


def test_export_contains_provenance_and_retired_turns(tmp_db, tmp_path):
    seed(tmp_db, vec=unit(0))
    seed(tmp_db, turn='new')
    maint.change_turn(tmp_db, 'old', 'new', apply=True)
    target = tmp_path / 'export.jsonl'
    maint.export_records(tmp_db, target)
    data = [json.loads(line) for line in target.read_text(encoding='utf-8').splitlines()]
    memories = [r['record'] for r in data if r['table'] == 'memories']
    assert len(memories) == 2
    assert memories[0]['role'] == 'assistant' and memories[0]['source'] == 'codex'
    assert memories[0]['session_id'] == 'chat-old'
    assert any(r['table'] == 'turn_lifecycle' for r in data)
    with pytest.raises(FileExistsError):
        maint.export_records(tmp_db, target)


def test_no_forced_weak_matches_by_default(tmp_db, monkeypatch):
    seed(tmp_db, text='unrelated', vec=at_cos(.75))
    monkeypatch.setattr(proc, 'embed_query', lambda _: unit(0))
    assert not proc.hybrid_search(tmp_db, 'nothing', n3memory._DEFAULT_CONFIG)['results']


@pytest.mark.parametrize('second,expected', [(.77, True), (.805, False)])
def test_semantic_rescue_requires_distinct_turn_margin(tmp_db, monkeypatch, second, expected):
    seed(tmp_db, text='best answer', vec=at_cos(.82))
    seed(tmp_db, rid='same-turn', text='best question', vec=at_cos(.815, axis=2))
    seed(tmp_db, turn='other', text='distractor', vec=at_cos(second, axis=3))
    monkeypatch.setattr(proc, 'embed_query', lambda _: unit(0))
    out = proc.hybrid_search(tmp_db, 'zzz', dict(n3memory._DEFAULT_CONFIG))
    assert bool(out['results']) is expected
    if expected:
        assert {r['turn_id'] for r in out['results']} == {'old'}
        assert not any(r['weak'] for r in out['results'])


def test_context_budget_and_traceable_ids():
    result = {'context_max_chars': 1000, 'results': [dict(id='record-1', turn_id='turn-1',
              score=.9, content='long evidence ' * 1000, role='user', source='codex')]}
    rendered = proc.render_memory_context(result, 'query')
    assert len(rendered) <= 1000
    assert 'record_id=record-1 turn_id=turn-1' in rendered
    assert 'Context truncated' in rendered


@pytest.mark.parametrize('pending', [False, True])
def test_model_mismatch_or_pending_reembed_uses_only_fts(tmp_db, monkeypatch, pending):
    seed(tmp_db, vec=unit(0))
    conn = db.get_connection(tmp_db)
    db.meta_set(conn, 'embed_model', 'old-model')
    if pending:
        db.meta_set(conn, 'reembed_model', 'old-model')
    conn.commit()
    conn.close()
    monkeypatch.setattr(proc, 'embed_query', lambda _: pytest.fail('must not compare incompatible vectors'))
    out = proc.hybrid_search(tmp_db, 'azure', dict(n3memory._DEFAULT_CONFIG,
                                               embed_model='old-model' if pending else 'new-model'))
    assert len(out['results']) == 1
    assert out['results'][0]['cos_sim'] == 0


def test_cli_preview_and_apply_without_starting_server(tmp_db, monkeypatch, capsys):
    seed(tmp_db)
    monkeypatch.setattr(n3memory, 'DB_PATH', tmp_db)
    monkeypatch.setattr(sys, 'argv', ['n3mc', '--forget-turn', 'old'])
    n3memory.main()
    assert json.loads(capsys.readouterr().out)['applied'] is False
    assert len(rows(tmp_db)) == 1
    monkeypatch.setattr(sys, 'argv', ['n3mc', '--forget-turn', 'old', '--yes'])
    n3memory.main()
    assert json.loads(capsys.readouterr().out)['applied'] is True
    assert not rows(tmp_db)


def test_reembed_does_not_restore_concurrently_forgotten_vectors(tmp_db, monkeypatch):
    seed(tmp_db, vec=unit(0))
    monkeypatch.setattr(n3memory, 'DB_PATH', tmp_db)
    monkeypatch.setattr(n3memory, '_request_shutdown', lambda _: None)
    monkeypatch.setattr(n3memory, '_clear_notice', lambda _: None)
    class Model:
        def encode(self, value, **kwargs):
            if isinstance(value, str):
                return unit(0)
            maint.change_turn(tmp_db, 'old', apply=True)
            return [unit(0) for _ in value]
    monkeypatch.setattr(proc, 'get_model', lambda _: Model())
    assert n3memory.cmd_reembed({'embed_model': 'synthetic'}) == 0
    assert not rows(tmp_db) and not rows(tmp_db, 'memories_vec')


def test_save_checks_model_under_write_lock_but_preserves_text(tmp_db):
    conn = db.get_connection(tmp_db)
    try:
        db.meta_set(conn, 'reembed_model', 'new')
        conn.commit()
        db.insert_memory_once(conn, 'a', '[user] keep this', '2026-11-18', 'owner',
                              turn_id='turn', embedding=unit(0), expected_embed_model='old')
        assert conn.execute('SELECT content FROM memories').fetchone()[0] == '[user] keep this'
        assert not conn.execute('SELECT * FROM memories_vec').fetchall()
        assert db.search_fts(conn, 'keep this')
    finally:
        conn.close()


def test_repair_rechecks_model_after_embedding(tmp_db, monkeypatch):
    seed(tmp_db)
    monkeypatch.setattr(n3memory, 'DB_PATH', tmp_db)
    monkeypatch.setattr(n3memory, '_srv_cfg', {'embed_model': 'synthetic'})
    def embed(_):
        conn = db.get_connection(tmp_db)
        db.meta_set(conn, 'reembed_model', 'new')
        conn.commit()
        conn.close()
        return unit(0)
    monkeypatch.setattr(proc, 'embed_passage', embed)
    n3memory._repair_db()
    assert len(rows(tmp_db)) == 1 and not rows(tmp_db, 'memories_vec')


def test_restore_checks_copied_bytes_against_manifest(tmp_db, tmp_path, monkeypatch):
    seed(tmp_db)
    config = tmp_path / 'config.json'
    config.write_text('{}')
    backup = tmp_path / 'backup'
    maint.backup_database(tmp_db, config, backup)
    original = maint.shutil.copy2
    def modified_source(src, dst):
        if Path(src).name == 'config.json':
            Path(src).write_text('{"changed":true}')
        return original(src, dst)
    monkeypatch.setattr(maint.shutil, 'copy2', modified_source)
    with pytest.raises(ValueError, match='copy verification'):
        maint.restore_database(backup, tmp_path / 'restored')
