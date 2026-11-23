"""Register this edition's hooks without altering other Codex handlers."""
import base64
import json
import os
import re
import shlex
import shutil
import sys
from datetime import datetime
from pathlib import Path
from tempfile import NamedTemporaryFile

_EVENTS = {'UserPromptSubmit': '--prompt', 'Stop': '--stop'}
_POWERSHELL_PREFIX = 'powershell.exe -NoLogo -NoProfile -NonInteractive -EncodedCommand '


def hooks_path() -> str:
    override = os.environ.get('N3MC_CODEX_HOOKS_PATH')
    if override:
        return os.path.expanduser(override)
    home = os.environ.get('CODEX_HOME') or '~/.codex'
    return str(Path(home).expanduser() / 'hooks.json')


def _command(flag: str) -> str:
    python = sys.executable
    if os.name == 'nt':
        return _windows_command(python, flag)
    return f'{shlex.quote(python)} -I -m n3memorycore.codex_entry {flag}'


def _windows_command(python: str, flag: str) -> str:
    if re.fullmatch(r'[A-Za-z0-9_:/\\.-]+', python):
        # A quoted executable expression needs a call operator in PowerShell.
        # A plain absolute path works in both PowerShell and cmd.exe.
        return f'{python} -I -m n3memorycore.codex_entry {flag}'
    literal = python.replace("'", "''")
    script = f"& '{literal}' -I -m n3memorycore.codex_entry {flag}; exit $LASTEXITCODE"
    encoded = base64.b64encode(script.encode('utf-16le')).decode('ascii')
    return _POWERSHELL_PREFIX + encoded


def _owned(handler: object, flag: str) -> bool:
    if not isinstance(handler, dict) or handler.get('type') != 'command':
        return False
    command = handler.get('command')
    if not isinstance(command, str):
        return False
    arguments = rf'-m\s+n3memorycore\.codex_entry\s+{re.escape(flag)}'
    if command.startswith(_POWERSHELL_PREFIX):
        try:
            script = base64.b64decode(command[len(_POWERSHELL_PREFIX):], validate=True).decode('utf-16le')
        except ValueError:
            return False
        return bool(re.fullmatch(rf"& '(?:[^']|'')+' -I {arguments}; exit \$LASTEXITCODE", script))
    return bool(re.fullmatch(
        rf'\s*(?:"[^"]+"|\'[^\']+\'|[^\s]+)\s+(?:-I\s+)?{arguments}\s*', command))


def merge_hooks(document: dict) -> dict:
    if not isinstance(document, dict):
        raise ValueError('hooks.json must contain a JSON object')
    hooks = document.setdefault('hooks', {})
    if not isinstance(hooks, dict):
        raise ValueError('hooks must be a JSON object')
    for event, flag in _EVENTS.items():
        groups = hooks.get(event, [])
        if not isinstance(groups, list):
            raise ValueError(f'hooks.{event} must be an array')
        kept = []
        for group in groups:
            handlers = group.get('hooks') if isinstance(group, dict) else None
            if not isinstance(handlers, list):
                kept.append(group)
                continue
            others = [handler for handler in handlers if not _owned(handler, flag)]
            if others or not handlers:
                kept.append({**group, 'hooks': others})
        kept.append({'hooks': [{
            'type': 'command',
            'command': _command(flag),
            'timeout': 120,
            'statusMessage': 'N3MC Free memory',
        }]})
        hooks[event] = kept
    return document


def install() -> int:
    path = Path(hooks_path())
    temporary = None
    try:
        try:
            original = path.read_bytes()
        except FileNotFoundError:
            original = None
        after = merge_hooks(json.loads(original) if original is not None else {})
        if original is not None and after == json.loads(original):
            print(f'Already registered: {path}')
            return 0

        path.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(mode='w', encoding='utf-8', newline='\n',
                                dir=path.parent, prefix='.n3mc-', delete=False) as file:
            temporary = Path(file.name)
            json.dump(after, file, ensure_ascii=False, indent=2)
            file.write('\n')
            file.flush()
            os.fsync(file.fileno())

        current = path.read_bytes() if path.exists() else None
        if current != original:
            raise ValueError('hooks.json changed during registration; retry')
        if original is not None:
            stamp = datetime.now().strftime('%Y%m%d%H%M%S%f')
            backup = path.with_name(f'{path.name}.bak-n3mc-{stamp}')
            shutil.copy2(path, backup)
            print(f'Backup: {backup}')
        os.replace(temporary, path)
        temporary = None
    except (OSError, ValueError) as exc:
        print(f'Cannot update {path}: {exc}', file=sys.stderr)
        return 1
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    print(f'Codex hooks registered: {path}')
    print('Review and trust the two N3MC Free handlers in Codex /hooks.')
    return 0
