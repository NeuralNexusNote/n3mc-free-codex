"""Read one Codex event from stdin and save or recall its conversation text."""
import os as _os
import sys as _sys

if __name__ == "__main__":
    # When invoked with -m outside a source checkout, exclude the current folder
    # before importing anything the working folder could shadow.
    _here = _os.path.normcase(_os.path.abspath(_os.getcwd()))
    _checkout = _os.path.normcase(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
    if _sys.path and _here != _checkout and _os.path.normcase(_os.path.abspath(_sys.path[0])) == _here:
        del _sys.path[0]

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from . import n3memory as memory
from .core.processor import sanitize_surrogates

_NO_SAVE = re.compile(
    r"(?:保存|記録|記憶)(?:を|は)?(?:しないで(?:ください)?|しなくて(?:も)?(?:いい|よい|大丈夫)|禁止|不要|やめて(?:ください)?|止めて(?:ください)?)"
    r"(?=[。！!、,\s]*$|[。！!\n])|"
    r"(?:記憶に|メモリに)残さないで(?:ください)?(?=[。！!、,\s]*$|[。！!\n])|"
    r"覚えないで(?:ください)?(?=[。！!、,\s]*$|[。！!\n])|"
    r"(?:^|[.!?\n]\s*)(?:please\s+)?(?:do not|don['’]t|never)\s+"
    r"(?:save|store|record|remember)\s+(?:(?:this|that)(?:\s+(?:reply|message|turn|conversation|chat))?|anything|our conversation|my (?:message|reply))"
    r"(?:\s+(?:in|to)\s+memory)?(?=\s*(?:[.!?,;]|$))|"
    r"(?:off the record|do not add (?:this|that) to memory)", re.I)
_SECRETS = re.compile(
    r"-----BEGIN (?:RSA |OPENSSH |EC |DSA )?PRIVATE KEY-----|"
    r"\b(?:sk-[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9_]{20,}|"
    r"github_pat_[A-Za-z0-9_]{20,}|AKIA[0-9A-Z]{16}|"
    r"AIza[0-9A-Za-z_-]{30,})\b|"
    r"\bBearer\s+[A-Za-z0-9._~+/-]{16,}\b", re.I)
_CREDENTIAL_ASSIGNMENT = re.compile(
    r"\b(?:api[_ -]?key|access[_ -]?token|secret|password|passwd|"
    r"パスワード|秘密鍵|認証トークン)\s*[:=：]\s*([^\s`;,]+)", re.I)


def _has_secrets(text):
    if _SECRETS.search(text):
        return True
    for match in _CREDENTIAL_ASSIGNMENT.finditer(text):
        value = match.group(1).strip("\"'")
        if re.match(r"(?:os\.(?:environ|getenv)|getenv\(|process\.env\b|\$|%|<)", value, re.I):
            continue
        if re.fullmatch(r"(?:x+|\*+|your[_-]?[a-z_-]+|placeholder|dummy|example|changeme)", value, re.I):
            continue
        if len(value) >= 6 and re.fullmatch(r"[A-Za-z0-9_./+~!@#$%^&*()=:-]+", value):
            return True
    return False


def _identifiers(payload):
    session = payload.get("session_id")
    thread = payload.get("thread_id")
    if session is not None and thread is not None and session != thread:
        raise ValueError("session_id and thread_id disagree")
    session = thread if session is None else session
    turn = payload.get("turn_id")
    if not all(isinstance(value, str) and value.strip() for value in (session, turn)):
        raise ValueError("session_id (or thread_id) and turn_id are required")
    return session, turn


def _strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)


def handle(event, raw):
    payload = sanitize_surrogates(json.loads(raw))
    if not isinstance(payload, dict):
        raise ValueError("hook input must be a JSON object")
    if payload.get("hook_event_name", event) != event:
        raise ValueError("hook_event_name does not match the entry point")
    session, turn = _identifiers(payload)
    is_prompt = event == "UserPromptSubmit"
    body_key = "prompt" if is_prompt else "last_assistant_message"
    message = payload.get(body_key)
    if message is not None and not isinstance(message, str):
        raise ValueError(f"{body_key} must be text or null")

    skip_key = hashlib.sha256(f"{session}\0{turn}".encode("utf-8")).hexdigest()
    marker = Path(memory.MEMORY_DIR) / f"skip_{skip_key}"
    if marker.exists():
        print("N3MC: turn excluded from memory.", file=_sys.stderr)
        return {"systemMessage": "N3MC: turn excluded from memory."}
    if any(_has_secrets(item) for item in _strings(payload)) or (
        is_prompt and message and _NO_SAVE.search(message)
    ):
        if is_prompt:
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.touch()
        print("N3MC: turn excluded from memory.", file=_sys.stderr)
        return {"systemMessage": "N3MC: turn excluded from memory."}

    # Audit before loading configuration, searching or touching the DB. Suppress
    # the entire line for excluded turns, including the raw payload.
    audited = memory._audit_append({
        "ts": datetime.now(timezone.utc).isoformat(),
        "hook": event, "raw": sanitize_surrogates(raw)[:4096], "payload": payload,
    })
    if not message or not message.strip():
        return None if audited else {"systemMessage": "N3MC could not write the local audit log."}

    cfg = memory.get_config()
    connected = memory._connection_target(cfg) is not None
    output = {}
    if is_prompt:
        if not connected and memory._use_server():
            try:
                memory._post("/repair", {"max_records": 20}, timeout=3)
            except Exception as exc:
                print(f"N3MC index repair failed ({type(exc).__name__}).", file=_sys.stderr)
        try:
            context = memory._search_text(message, session, cfg=cfg)
        except Exception as exc:
            print(f"N3MC recall failed ({type(exc).__name__}).", file=_sys.stderr)
            context = memory._placeholder("_(memory search unavailable)_", [])
        output["hookSpecificOutput"] = {
            "hookEventName": event,
            "additionalContext": context,
        }

    try:
        if connected:
            from .project import detect_project
            cwd = payload.get("cwd")
            project = detect_project(cwd) if isinstance(cwd, str) and cwd.strip() else None
            _, failed = memory._save_text("user" if is_prompt else "claude", message, turn, session,
                                          project=project)
        else:
            _, failed = memory._save_text("user" if is_prompt else "claude", message, turn, session)
    except Exception as exc:
        if not is_prompt:
            raise
        print(f"N3MC prompt save failed ({type(exc).__name__}).", file=_sys.stderr)
        failed = True
    if failed:
        if not is_prompt:
            raise RuntimeError("physical save failed")
        output["systemMessage"] = "N3MC could not save the complete prompt. Recalled context is still available."
    elif not audited:
        output["systemMessage"] = "N3MC could not write the local audit log."

    if not is_prompt:
        memory.cmd_stop()
    return output or None


def _run(event):
    memory._reconfigure_streams()
    try:
        response = handle(event, _sys.stdin.read())
        if response is not None:
            print(json.dumps(response, ensure_ascii=False))
        return 0
    except ValueError as exc:
        # JSONDecodeError inherits from ValueError. Its input text is omitted.
        detail = "invalid UTF-8 JSON input" if isinstance(exc, (json.JSONDecodeError, UnicodeError)) else str(exc)
        print(f"N3MC hook failed: {detail}.", file=_sys.stderr)
        return 1
    except Exception as exc:
        print(f"N3MC hook failed ({type(exc).__name__}).", file=_sys.stderr)
        return 1


def prompt_main():
    return _run("UserPromptSubmit")


def stop_main():
    return _run("Stop")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--prompt", action="store_true")
    mode.add_argument("--stop", action="store_true")
    args = parser.parse_args()
    return prompt_main() if args.prompt else stop_main()


if __name__ == "__main__":
    _sys.exit(main())
