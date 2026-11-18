"""Idempotent installer for Codex's global hooks.json."""
import json
import os
import shutil
import sys
from datetime import datetime


def hooks_path():
    return os.environ.get('N3MC_CODEX_HOOKS_PATH') or os.path.join(
        os.path.expanduser('~'), '.codex', 'hooks.json')


def merge_hooks(document):
    if not isinstance(document, dict):
        raise ValueError('hooks.json must contain a JSON object')
    hooks = document.setdefault('hooks', {})
    if not isinstance(hooks, dict):
        raise ValueError('hooks must be a JSON object')
    python = sys.executable
    if ' ' in python:
        python = f'"{python}"'
    for event, flag in (('UserPromptSubmit', '--prompt'), ('Stop', '--stop')):
        entries = hooks.get(event, [])
        if not isinstance(entries, list):
            raise ValueError(f'hooks.{event} must be an array')
        kept = []
        for entry in entries:
            if not isinstance(entry, dict) or not isinstance(entry.get('hooks'), list):
                kept.append(entry)
                continue
            inner = [item for item in entry['hooks'] if not (
                isinstance(item, dict) and
                'n3memorycore.codex_entry' in str(item.get('command', '')))]
            if inner:
                kept.append({**entry, 'hooks': inner})
        kept.append({'hooks': [{
            'type': 'command',
            'command': f'{python} -m n3memorycore.codex_entry {flag}',
            'timeout': 120,
            'statusMessage': 'N3MC Free memory',
        }]})
        hooks[event] = kept
    return document


def install():
    path = hooks_path()
    try:
        with open(path, encoding='utf-8') as f:
            before = json.load(f)
    except FileNotFoundError:
        before = {}
    except (OSError, ValueError) as exc:
        print(f'Cannot read {path}: {exc}', file=sys.stderr)
        return 1
    try:
        after = merge_hooks(json.loads(json.dumps(before)))
    except ValueError as exc:
        print(f'Cannot update {path}: {exc}', file=sys.stderr)
        return 1
    if after == before:
        print(f'Already registered: {path}')
        return 0
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if os.path.exists(path):
        backup = path + '.bak-n3mc-' + datetime.now().strftime('%Y%m%d%H%M%S')
        shutil.copy2(path, backup)
        print(f'Backup: {backup}')
    temp = path + '.tmp-n3mc'
    with open(temp, 'w', encoding='utf-8') as f:
        json.dump(after, f, ensure_ascii=False, indent=2)
        f.write('\n')
        f.flush()
        os.fsync(f.fileno())
    os.replace(temp, path)
    print(f'Codex hooks registered: {path}')
    print('Review and trust both hooks in Codex before using automatic capture.')
    return 0
