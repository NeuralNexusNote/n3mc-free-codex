import sys
import os

# Keep checkout execution working and exclude unrelated working directories
# before importing the modules used by this entry point.
if __name__ == '__main__' and sys.path:
    here = os.path.normcase(os.path.realpath(os.getcwd()))
    checkout = os.path.normcase(os.path.realpath(os.path.dirname(os.path.dirname(__file__))))
    if here != checkout and os.path.normcase(os.path.realpath(sys.path[0])) == here:
        del sys.path[0]

# spec §3: reconfigure streams to UTF-8 at module top — before any stdin read
for _s_name in ("stdin", "stdout", "stderr"):
    _s = getattr(sys, _s_name, None)
    if _s is not None and hasattr(_s, 'reconfigure'):
        try:
            _s.reconfigure(encoding='utf-8')
        except Exception:
            pass

import json
import subprocess
from datetime import datetime, timezone

from .paths import MEMORY_DIR, AUDIT_LOG, python_cmd


def _write_audit(hook: str, raw: str, payload: dict) -> None:
    # spec §5.4: audit.log write failures go to stderr and never stop a hook
    try:
        from .core.processor import sanitize_surrogates
        os.makedirs(os.path.dirname(AUDIT_LOG), exist_ok=True)
        record = json.dumps({
            'ts':      datetime.now(timezone.utc).isoformat(),
            'hook':    hook,
            'raw':     sanitize_surrogates(raw[:4096]),
            'payload': sanitize_surrogates(payload),
        }, ensure_ascii=False)
        with open(AUDIT_LOG, 'a', encoding='utf-8') as f:
            f.write(record + '\n')
    except Exception as e:
        print(f"Warning: audit log write failed: {e}", file=sys.stderr)


def main():
    raw = sys.stdin.read()

    try:
        payload = json.loads(raw)
    except Exception:
        payload = {'raw': raw}

    # spec §5: Step 0 — audit log written before any other processing
    _write_audit('Stop', raw, payload)

    # spec §5: --save-claude-turn first, then --stop (both synchronous)
    # Do NOT use --buffer -: Stop hook already consumed stdin above.
    proc = subprocess.run(
        [*python_cmd(), '-m', 'n3memorycore.n3memory', '--save-claude-turn'],
        input=raw,
        encoding='utf-8',
        capture_output=False,
    )

    subprocess.run(
        [*python_cmd(), '-m', 'n3memorycore.n3memory', '--stop'],
        capture_output=False,
    )

    sys.exit(proc.returncode)


if __name__ == '__main__':
    main()
