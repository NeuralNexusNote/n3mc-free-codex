"""Codex UserPromptSubmit and Stop entry point.

Codex provides a thread_id and the same turn_id to both hooks. We use those
IDs directly, so concurrent chats cannot exchange Q-A pairing state.
"""
import hashlib
import json
import os
import re
import sys

for _name in ('stdin', 'stdout', 'stderr'):
    _stream = getattr(sys, _name, None)
    if _stream is not None and hasattr(_stream, 'reconfigure'):
        _stream.reconfigure(encoding='utf-8')

from .core.processor import sanitize_surrogates
from .paths import MEMORY_DIR

_NO_SAVE = re.compile(
    r"(?:保存|記録|記憶)(?:を|は)?(?:しない|しないで|しなくて|禁止|不要)|"
    r"(?:記憶に|メモリに)残さない|覚えないで|"
    r"(?:do not|don't|never)\s+(?:save|store|record|remember)|"
    r"(?:off the record|do not add (?:this|that) to memory)", re.I)
_SECRETS = re.compile(
    r"-----BEGIN (?:RSA |OPENSSH |EC |DSA )?PRIVATE KEY-----|"
    r"\b(?:sk-[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9_]{20,}|"
    r"github_pat_[A-Za-z0-9_]{20,}|AKIA[0-9A-Z]{16}|"
    r"AIza[0-9A-Za-z_-]{30,})\b|"
    r"\bBearer\s+[A-Za-z0-9._~+/-]{16,}\b|"
    r"\b(?:api[_ -]?key|access[_ -]?token|secret|password|passwd|"
    r"パスワード|秘密鍵|認証トークン)\s*[:=：]\s*[^\s]{6,}", re.I)


def _skip_path(data):
    thread = str(data.get('thread_id') or data.get('session_id') or '')
    turn = str(data.get('turn_id') or '')
    if not thread or not turn:
        return None
    key = hashlib.sha256((thread + '\0' + turn).encode('utf-8')).hexdigest()
    return os.path.join(MEMORY_DIR, 'skip_' + key)


def _mark_skip(data):
    path = _skip_path(data)
    if path:
        os.makedirs(MEMORY_DIR, exist_ok=True)
        with open(path, 'w', encoding='ascii') as f:
            f.write('skip\n')


def _was_skipped(data):
    path = _skip_path(data)
    return bool(path and os.path.exists(path))


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in ('--prompt', '--stop'):
        raise SystemExit('usage: python -m n3memorycore.codex_entry --prompt|--stop')
    try:
        data = json.load(sys.stdin)
        if not isinstance(data, dict):
            raise ValueError('hook input must be a JSON object')
        data = sanitize_surrogates(data)
        text = data.get('prompt') or data.get('message') or ''
        if not isinstance(text, str):
            text = json.dumps(text, ensure_ascii=False)
        if sys.argv[1] == '--prompt':
            if _NO_SAVE.search(text) or _SECRETS.search(text):
                _mark_skip(data)
                return
            from .n3memory import _load_config, cmd_hook_submit
            sys.stdin = _JsonInput(data)
            cmd_hook_submit(_load_config())
        else:
            if _was_skipped(data):
                return
            answer = data.get('last_assistant_message') or ''
            if isinstance(answer, str) and _SECRETS.search(answer):
                return
            from .n3memory import _load_config, cmd_save_claude_turn, _housekeeping
            cfg = _load_config()
            sys.stdin = _JsonInput(data)
            cmd_save_claude_turn(cfg)
            _housekeeping()
    except Exception as exc:
        print(f'N3MC hook failed: {type(exc).__name__}: {exc}', file=sys.stderr)
        raise SystemExit(1)


class _JsonInput:
    def __init__(self, data):
        self.data = data

    def read(self):
        return json.dumps(self.data, ensure_ascii=False)


def prompt_main():
    sys.argv = [sys.argv[0], '--prompt']
    main()


def stop_main():
    sys.argv = [sys.argv[0], '--stop']
    main()


if __name__ == '__main__':
    main()
