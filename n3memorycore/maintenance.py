"""Local memory lifecycle and portable SQLite snapshots. No model required."""
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
from datetime import datetime, timezone

from .core.database import get_connection, init_db, migrate_schema


def ready_connection(path):
    if not Path(path).is_file():
        raise FileNotFoundError(f'Memory database not found: {path}')
    conn = get_connection(str(path))
    try:
        init_db(conn)
        migrate_schema(conn)
        return conn
    except BaseException:
        conn.close()
        raise


def change_turn(path, turn_id, replacement=None, apply=False):
    """Preview by default; atomic supersession or physical deletion plus tombstone."""
    conn = ready_connection(path)
    try:
        conn.execute('BEGIN IMMEDIATE' if apply else 'BEGIN')
        old = conn.execute('SELECT rowid, owner_id FROM memories WHERE turn_id = ?',
                           (turn_id,)).fetchall()
        state = conn.execute('SELECT state, replacement_turn_id FROM turn_lifecycle WHERE turn_id = ?',
                             (turn_id,)).fetchone()
        if not old and not (state and state['state'] == 'forgotten' and not replacement):
            raise ValueError('Source turn not found')
        if replacement:
            if turn_id == replacement:
                raise ValueError('A turn cannot replace itself')
            new = conn.execute('SELECT owner_id FROM memories WHERE turn_id = ?',
                               (replacement,)).fetchall()
            if not new:
                raise ValueError('Replacement turn not found')
            if conn.execute('SELECT 1 FROM turn_lifecycle WHERE turn_id = ?', (replacement,)).fetchone():
                raise ValueError('Replacement must be an active turn')
            if state and (state['state'] != 'superseded' or state['replacement_turn_id'] != replacement):
                raise ValueError('Source is already retired; its correction cannot be overwritten')
            if len({r['owner_id'] for r in old + new}) != 1:
                raise ValueError('Turns must have the same owner')
        result = dict(action='supersede' if replacement else 'forget', turn_id=turn_id,
                      replacement_turn_id=replacement, records=len(old), applied=apply)
        if apply:
            if not replacement:
                ids = [(r['rowid'],) for r in old]
                for table in ('memories_vec', 'memories_fts', 'memories_fts_bi', 'memories'):
                    conn.executemany(f'DELETE FROM {table} WHERE rowid = ?', ids)
            conn.execute('INSERT OR REPLACE INTO turn_lifecycle VALUES (?, ?, ?, ?)',
                         (turn_id, 'superseded' if replacement else 'forgotten', replacement,
                          datetime.now(timezone.utc).isoformat()))
            conn.commit()
        else:
            conn.rollback()
        return result
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def _sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def backup_database(db_path, config_path, destination):
    """Online backup including WAL writes; exclusive destination, manifest last."""
    source = Path(db_path).resolve()
    config = Path(config_path)
    if not source.is_file() or not config.is_file():
        raise FileNotFoundError('Database and config.json must both exist')
    config_bytes = config.read_bytes()
    if not isinstance(json.loads(config_bytes), dict):
        raise ValueError('Configuration must be a JSON object')
    target = Path(destination).resolve()
    target.mkdir(parents=True, exist_ok=False)
    src = sqlite3.connect(source.as_uri() + '?mode=ro', uri=True)
    dst = sqlite3.connect(target / 'n3memory.db')
    try:
        src.backup(dst)
        if dst.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise ValueError('Backup integrity check failed')
        count = dst.execute('SELECT COUNT(*) FROM memories').fetchone()[0]
    finally:
        dst.close()
        src.close()
    if config.read_bytes() != config_bytes:
        raise RuntimeError('Configuration changed during backup; retry into a new directory')
    (target / 'config.json').write_bytes(config_bytes)
    manifest = dict(format='n3mc-snapshot-v1', records=count,
                    created_at=datetime.now(timezone.utc).isoformat(),
                    sha256={name: _sha(target / name) for name in ('n3memory.db', 'config.json')})
    (target / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    return dict(path=str(target), records=count)


def restore_database(snapshot, destination):
    """Validate before writing; restore into a new home, never over live state."""
    source = Path(snapshot).resolve()
    manifest = json.loads((source / 'manifest.json').read_text(encoding='utf-8'))
    if manifest.get('format') != 'n3mc-snapshot-v1':
        raise ValueError('Unsupported backup format')
    for name in ('n3memory.db', 'config.json'):
        if _sha(source / name) != manifest['sha256'].get(name):
            raise ValueError(f'Backup checksum mismatch: {name}')
    target = Path(destination).resolve()
    target.mkdir(parents=True, exist_ok=False)
    memory = target / '.memory'
    memory.mkdir()
    shutil.copy2(source / 'n3memory.db', memory / 'n3memory.db')
    shutil.copy2(source / 'config.json', target / 'config.json')
    for name, dst in (('n3memory.db', memory / 'n3memory.db'),
                      ('config.json', target / 'config.json')):
        if manifest['sha256'][name] != _sha(dst):
            raise ValueError('Restore copy verification failed')
    conn = sqlite3.connect((memory / 'n3memory.db').as_uri() + '?mode=ro', uri=True)
    try:
        if conn.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise ValueError('Restored database integrity check failed')
        count = conn.execute('SELECT COUNT(*) FROM memories').fetchone()[0]
        if count != manifest['records']:
            raise ValueError('Restored record count differs from manifest')
    finally:
        conn.close()
    return dict(path=str(target), records=count)


def export_records(path, destination):
    """Metadata-complete text archive; use SQLite backup for a restorable snapshot."""
    conn = ready_connection(path)
    try:
        conn.execute('BEGIN')
        with Path(destination).open('x', encoding='utf-8', newline='\n') as stream:
            for table in ('memories', 'turn_lifecycle', 'meta'):
                for row in conn.execute(f'SELECT * FROM {table}'):
                    stream.write(json.dumps(dict(table=table, record=dict(row)), ensure_ascii=False) + '\n')
        conn.rollback()
    finally:
        conn.close()
    return dict(path=str(Path(destination).resolve()))
