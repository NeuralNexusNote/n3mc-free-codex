"""The approval waiter must require a real matched prompt/reply pair."""

import sqlite3
import sys
from pathlib import Path
from types import SimpleNamespace

from tools import wait_for_hook_trust as waiter


def _database(path: Path, rows: list[tuple[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.execute('CREATE TABLE memories (turn_id TEXT, content TEXT, agent_name TEXT)')
        conn.executemany(
            'INSERT INTO memories VALUES (?, ?, ?)',
            [(turn, content, 'codex') for turn, content in rows],
        )


def test_saved_pair_requires_both_roles_in_same_turn(tmp_path):
    database = tmp_path / 'n3memory.db'
    marker = 'N3MC_TRUST_PROBE_abc'
    _database(database, [
        ('turn-a', f'[user] {marker}'),
        ('turn-b', '[claude] unrelated'),
    ])
    assert not waiter.saved_pair(database, marker)
    with sqlite3.connect(database) as conn:
        conn.execute('INSERT INTO memories VALUES (?, ?, ?)',
                     ('turn-a', '[claude] reply', 'codex'))
    assert waiter.saved_pair(database, marker)


def test_probe_uses_disposable_home_and_never_bypasses_trust(tmp_path, monkeypatch):
    work = tmp_path / 'work'
    data = tmp_path / 'data'
    work.mkdir()

    def fake_run(command, **kwargs):
        assert command[:2] == ['codex', 'exec']
        assert '--ephemeral' in command
        assert '--dangerously-bypass-hook-trust' not in command
        assert kwargs['env']['N3MC_FREE_CODEX_HOME'] == str(data)
        marker = command[-1].split()[-1]
        _database(data / '.memory' / 'n3memory.db', [
            ('turn-1', f'[user] {marker}'),
            ('turn-1', '[claude] reply'),
        ])
        return SimpleNamespace(returncode=0, stdout='', stderr='')

    monkeypatch.setattr(waiter.subprocess, 'run', fake_run)
    assert waiter.probe(['codex'], work, data, 30)


def test_resolver_uses_npx_only_when_codex_is_absent(monkeypatch):
    npx_name = 'npx.cmd' if waiter.os.name == 'nt' else 'npx'
    monkeypatch.setattr(waiter.shutil, 'which',
                        lambda name: {npx_name: '/node/npx'}.get(name))
    assert waiter.resolve_codex_command() == [
        '/node/npx', '--yes', '@openai/codex'
    ]


def test_wait_continues_after_approval_without_new_user_message(monkeypatch):
    attempts = iter((False, True))
    monkeypatch.setattr(sys, 'argv', ['wait_for_hook_trust.py', '--codex', 'codex'])
    monkeypatch.setattr(waiter, 'registered', lambda: True)
    monkeypatch.setattr(waiter, 'probe', lambda *_: next(attempts))
    monkeypatch.setattr(waiter, 'stop_probe_server', lambda *_: None)
    monkeypatch.setattr(waiter.time, 'sleep', lambda *_: None)
    assert waiter.main() == 0
