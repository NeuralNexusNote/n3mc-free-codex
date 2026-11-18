"""Isolated real-server test of Codex hook processes (not Codex UI trust)."""
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).parent


def main():
    with tempfile.TemporaryDirectory(prefix='hooks-', dir=OUT) as tmp:
        home = Path(tmp).resolve()
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        config = {'owner_id': 'review-owner', 'local_id': 'review-local',
                  'server_port': port, 'embed_model': 'intfloat/multilingual-e5-base'}
        (home / 'config.json').write_text(json.dumps(config), encoding='utf-8')
        env = dict(os.environ, N3MC_HOME=str(home), HF_HUB_OFFLINE='1',
                   TRANSFORMERS_OFFLINE='1', PYTHONIOENCODING='utf-8')
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        def request(path, payload=None):
            data = json.dumps(payload).encode() if payload is not None else None
            req = urllib.request.Request(f'http://127.0.0.1:{port}{path}', data=data,
                                         headers={'Content-Type': 'application/json'})
            with opener.open(req, timeout=5) as response:
                return json.load(response)
        def hook(flag, payload):
            result = subprocess.run([sys.executable, '-m', 'n3memorycore.codex_entry', flag],
                                    input=json.dumps(payload, ensure_ascii=False),
                                    encoding='utf-8', capture_output=True, cwd=ROOT, env=env,
                                    timeout=120, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            assert result.returncode == 0, result.stderr
            return result.stdout
        with (OUT / 'hook_server.log').open('w', encoding='utf-8') as log:
            server = subprocess.Popen([sys.executable, '-m', 'n3memorycore.n3memory', '--run-server'],
                                      cwd=ROOT, env=env, stdout=log, stderr=log,
                                      creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            try:
                deadline = time.monotonic() + 90
                while True:
                    try:
                        health = request('/health')
                        assert Path(health['root']).resolve() == home
                        break
                    except OSError:
                        assert server.poll() is None, 'server exited during startup'
                        if time.monotonic() >= deadline:
                            raise TimeoutError('isolated server startup timed out')
                        time.sleep(0.2)
                first = dict(thread_id='chat-a', turn_id='turn-a')
                hook('--prompt', dict(first, prompt='検証用の合言葉は琥珀フクロウ5821です。'))
                answer = dict(first, last_assistant_message='合言葉は琥珀フクロウ5821として記録します。')
                hook('--stop', answer)
                hook('--stop', answer)  # Retries must be idempotent.
                second = dict(thread_id='chat-b', turn_id='turn-b')
                recalled = hook('--prompt', dict(second, prompt='琥珀フクロウの合言葉は？'))
                assert '5821' in recalled and '# Recalled Memory Context' in recalled
                hook('--stop', dict(second, last_assistant_message='合言葉は5821です。'))
                skip = dict(thread_id='chat-b', turn_id='turn-skip')
                hook('--prompt', dict(skip, prompt='このターンは保存しないでください。'))
                hook('--stop', dict(skip, last_assistant_message='保存しません。'))
                listing = subprocess.run([sys.executable, '-m', 'n3memorycore.n3memory',
                                          '--list', '--format', 'jsonl'], capture_output=True,
                                         encoding='utf-8', cwd=ROOT, env=env, timeout=30,
                                         creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                assert listing.returncode == 0, listing.stderr
                records = [json.loads(line) for line in listing.stdout.splitlines() if line.strip()]
                assert len(records) == 4, records
                # CLI JSONL is a display/export of four columns; check pairing
                # metadata in the isolated database, where it is actually stored.
                conn = sqlite3.connect(home / '.memory' / 'n3memory.db')
                conn.row_factory = sqlite3.Row
                try:
                    records = [dict(r) for r in conn.execute(
                        'SELECT turn_id, session_id FROM memories')]
                finally:
                    conn.close()
                for turn, chat in [('turn-a', 'chat-a'), ('turn-b', 'chat-b')]:
                    pair = [r for r in records if r['turn_id'] == turn]
                    assert len(pair) == 2 and all(r['session_id'] == chat for r in pair)
                report = dict(result='passed', records=len(records),
                              paired_turns=2, separate_chats=2,
                              stop_retry_deduplicated=True, do_not_save_respected=True,
                              cross_process_recall=True, codex_ui_trust_verified=False)
                (OUT / 'hook_process_results.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
                print(json.dumps(report, indent=2))
            finally:
                if server.poll() is None:
                    try:
                        request('/shutdown', {'root': str(home)})
                        server.wait(timeout=15)
                    except Exception:
                        server.terminate()
                        server.wait(timeout=15)


if __name__ == '__main__':
    main()
