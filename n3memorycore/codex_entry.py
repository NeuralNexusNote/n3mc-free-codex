"""Codex hook adapter. The hook payload is the conversation boundary."""
import hashlib
import io
import json
import os
import re
import sys
from contextlib import redirect_stdout
from pathlib import Path

from .core.processor import add_chunk_prefixes, chunk_text, purify_text, sanitize_surrogates
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


def _handle(flag: str, data: dict) -> dict | None:
    from . import n3memory as memory

    event = 'UserPromptSubmit' if flag == '--prompt' else 'Stop'
    if data.get('hook_event_name', event) != event:
        raise ValueError('unexpected Codex hook event')
    session = data.get('session_id') or data.get('thread_id')
    turn = data.get('turn_id')
    if not all(isinstance(value, str) and value.strip() for value in (session, turn)):
        raise ValueError('Codex hook requires session_id and turn_id')

    key = hashlib.sha256(f'{session}\0{turn}'.encode('utf-8')).hexdigest()
    marker = Path(MEMORY_DIR) / f'skip_{key}'
    if marker.exists():
        return None
    is_prompt = flag == '--prompt'
    message = data.get('prompt' if is_prompt else 'last_assistant_message')
    if not isinstance(message, str) or not message.strip():
        return None
    if is_prompt and (_NO_SAVE.search(message) or _SECRETS.search(message)
                      or message.lstrip().startswith(memory._SYSTEM_PROMPT_PREFIXES)):
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.touch()
        return None
    if not is_prompt and _SECRETS.search(message):
        return None

    cfg = memory._load_config()
    server_ready = memory.ensure_server(cfg)
    response = None
    if is_prompt:
        if server_ready:
            try:
                memory._post(cfg, '/repair', {'max_records': memory._HOOK_REPAIR_MAX_RECORDS},
                             timeout=3)
            except Exception:
                memory.logger.warning('Index repair failed during Codex prompt hook')
        query = message[:cfg.get('search_query_max_chars', 2000)]
        output = io.StringIO()
        with redirect_stdout(output):
            memory._do_search(query, cfg, current_session=session, local_fallback=True)
        context = output.getvalue().strip()
        if context:
            response = {'hookSpecificOutput': {
                'hookEventName': event,
                'additionalContext': context,
            }}

    # Keep the existing stored prefix for compatibility with DB and ranking.
    role = 'user' if is_prompt else 'claude'
    try:
        for chunk in add_chunk_prefixes(chunk_text(purify_text(message)), role):
            memory._do_buffer(chunk, cfg, agent_name='codex', session_id=session, turn_id=turn,
                              timeout=8)
    except RuntimeError:
        if response is None:
            raise
        # Codex consumes context only from a successful hook response. Keep
        # the completed search and surface the independent save error.
        response['systemMessage'] = 'N3MC could not save the complete prompt. Recalled context is still available.'

    if not is_prompt:
        memory.cmd_stop(cfg)
    return response


def _run(flag: str) -> None:
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8')
    try:
        data = json.load(sys.stdin)
        if not isinstance(data, dict):
            raise ValueError('hook input must be a JSON object')
        output = _handle(flag, sanitize_surrogates(data))
        if output is not None:
            print(json.dumps(output, ensure_ascii=False))
    except Exception as exc:
        print(f'N3MC hook failed ({type(exc).__name__}).', file=sys.stderr)
        raise SystemExit(1) from None


def main() -> None:
    if len(sys.argv) != 2 or sys.argv[1] not in ('--prompt', '--stop'):
        raise SystemExit('usage: python -I -m n3memorycore.codex_entry --prompt|--stop')
    _run(sys.argv[1])


def prompt_main() -> None:
    _run('--prompt')


def stop_main() -> None:
    _run('--stop')


if __name__ == '__main__':
    main()
