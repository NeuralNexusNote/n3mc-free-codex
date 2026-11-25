"""Wait for real Codex hooks to save both sides of a disposable probe turn.

Run this in the implementing Codex task after ``n3mc-free-codex --init`` and before
asking the user to trust the hooks. A successful exit lets that same task
continue into the live evaluation and pytest without another user message.
"""

import argparse
import json
import os
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path
from urllib import request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from n3memorycore_free_codex.codex_install import _owned, hooks_path


def resolve_codex_command(explicit: str | None = None) -> list[str] | None:
    """Use an existing CLI, or let npx fetch the official package automatically."""
    if explicit:
        return [explicit]
    installed = shutil.which('codex')
    if installed:
        return [installed]
    npx = shutil.which('npx.cmd' if os.name == 'nt' else 'npx')
    if npx:
        return [npx, '--yes', '@openai/codex']
    return None


def registered() -> bool:
    """Check both Free handlers in the real global Codex hooks file."""
    try:
        document = json.loads(Path(hooks_path()).read_text(encoding='utf-8'))
        hooks = document['hooks']
        return all(
            sum(
                _owned(item, flag)
                for group in hooks.get(event, [])
                for item in group.get('hooks', [])
            ) == 1
            for event, flag in (('UserPromptSubmit', '--prompt'), ('Stop', '--stop'))
        )
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return False


def saved_pair(database: Path, marker: str) -> bool:
    """A prompt and reply from one actual Codex turn prove both hooks ran."""
    if not database.is_file():
        return False
    try:
        with sqlite3.connect(f'{database.resolve().as_uri()}?mode=ro', uri=True) as conn:
            rows = conn.execute(
                'SELECT turn_id, content FROM memories WHERE agent_name = ?', ('codex',)
            ).fetchall()
    except sqlite3.Error:
        return False
    turns = {
        turn_id for turn_id, content in rows
        if turn_id and content.startswith('[user]') and marker in content
    }
    return any(
        turn_id in turns and content.startswith('[claude]')
        for turn_id, content in rows
    )


def probe(codex: list[str], work: Path, data: Path, timeout: int) -> bool:
    marker = f'N3MC_TRUST_PROBE_{uuid.uuid4().hex}'
    env = os.environ.copy()
    env['N3MC_FREE_CODEX_HOME'] = str(data)
    command = [
        *codex, 'exec', '--json', '--ephemeral', '--sandbox', 'workspace-write',
        '--skip-git-repo-check', '-C', str(work),
        f'Reply with only this marker: {marker}',
    ]
    try:
        result = subprocess.run(
            command, env=env, capture_output=True, text=True,
            encoding='utf-8', errors='replace', timeout=timeout, check=False,
        )
    except subprocess.TimeoutExpired:
        return False
    if result.returncode:
        detail = (result.stderr or result.stdout).strip()[-800:]
        raise RuntimeError(f'Codex probe failed (exit {result.returncode}): {detail}')
    return saved_pair(data / '.memory' / 'n3memory.db', marker)


def stop_probe_server(data: Path) -> None:
    """Ask only a server owned by this disposable data root to shut down."""
    try:
        config = json.loads((data / 'config.json').read_text(encoding='utf-8'))
        port = int(config.get('server_port', 18526))
        opener = request.build_opener(request.ProxyHandler({}))
        with opener.open(f'http://127.0.0.1:{port}/health', timeout=3) as response:
            health = json.load(response)
        if health.get('status') != 'ok' or Path(health.get('root', '')).resolve() != data.resolve():
            return
        body = json.dumps({'root': str(data)}).encode('utf-8')
        call = request.Request(
            f'http://127.0.0.1:{port}/shutdown', data=body,
            headers={'Content-Type': 'application/json'}, method='POST',
        )
        opener.open(call, timeout=3).close()
    except (OSError, ValueError, KeyError, AttributeError, TypeError):
        pass  # No server, or another root owns the port.


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--codex', help='Existing Codex CLI path (optional)')
    parser.add_argument('--wait-seconds', type=int, default=900)
    parser.add_argument('--interval-seconds', type=int, default=90)
    parser.add_argument('--probe-timeout', type=int, default=180)
    args = parser.parse_args()
    codex = resolve_codex_command(args.codex)
    if not codex:
        print('No Codex CLI or npx is available; skipping the CLI probe.', file=sys.stderr)
        return 3
    if len(codex) > 1:
        print('Codex CLI is absent; npx will download @openai/codex automatically.', flush=True)
    if min(args.wait_seconds, args.interval_seconds, args.probe_timeout) <= 0:
        parser.error('all time limits must be positive')
    if not registered():
        print('N3MC Free hooks are missing or duplicated; run n3mc-free-codex --init first.', file=sys.stderr)
        return 2

    deadline = time.monotonic() + args.wait_seconds
    with tempfile.TemporaryDirectory(prefix='n3mc-hook-trust-',
                                     ignore_cleanup_errors=True) as root:
        work = Path(root) / 'work'
        data = Path(root) / 'data'
        work.mkdir()
        data.mkdir()
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        (data / "config.json").write_text(json.dumps({"server_port": port}), encoding="utf-8")
        try:
            while True:
                if probe(codex, work, data, args.probe_timeout):
                    print('Both N3MC Free hooks ran in a real Codex turn. Continue with §6 and §7.')
                    return 0
                if time.monotonic() >= deadline:
                    print('Hook trust was not verified before the deadline.', file=sys.stderr)
                    return 1
                print('Waiting for both hooks to be trusted...', flush=True)
                time.sleep(min(args.interval_seconds, max(0, deadline - time.monotonic())))
        finally:
            stop_probe_server(data)


if __name__ == '__main__':
    raise SystemExit(main())
