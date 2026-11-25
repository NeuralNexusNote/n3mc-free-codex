"""Data-flow trace: nothing is lost between the hook input and the stored records (no model)."""
import io
import json
import random
import re
import sqlite3

import pytest
from fastapi.testclient import TestClient

from n3memorycore_free_codex import codex_entry
from n3memorycore_free_codex import n3memory as n3m
from n3memorycore_free_codex.core import processor as p

ALPHABET = ["あ", "い", "。", "！", "？", ".", "!", "?", " ", "\n", "\n\n",
            "\r\n", "\t", "x", "Y", "漢", "é", "😀", "「", "」", "9"]


def _rebuild(chunks):
    got = ""
    for chunk in chunks:
        overlap = min(40, len(got))
        assert not overlap or got.endswith(chunk[:overlap])
        got += chunk[overlap:]
    return got


def test_chunking_keeps_every_character_in_order_and_under_the_limit():
    rnd = random.Random(7)
    for _ in range(400):
        text = "".join(rnd.choice(ALPHABET) for _ in range(rnd.choice([5, 300, 450, 900, 2500])))
        chunks = p.chunk_text(text)
        assert all(len(c) <= 400 for c in chunks)
        assert _rebuild(chunks) == text


def test_special_characters_survive_save(conn):
    text = " \t%s %% {x} $1 \n \"q\" <tag> & 😀 tab\there\r\nCRLF\r\n日本語の文章です。\r\n "
    n3m._save_text("user", text, "T")
    stored = conn.execute("SELECT content FROM memories").fetchone()[0]
    assert stored == "[user] " + text


def test_long_prompt_is_stored_in_full(conn):
    text = "\r\n \r\n".join(f"  第{i}章。\t" + "本文です。  " * 40 for i in range(1, 30))
    n3m._save_text("user", text, "T")
    stored = [re.sub(r"^\[user( \d+/\d+)?\] ", "", r[0]) for r in conn.execute(
        "SELECT content FROM memories ORDER BY rowid")]
    assert _rebuild(stored) == text


def test_prompt_json_contains_ranked_hit_even_if_exchange_lookup_fails(
    conn, use_fake_embed, monkeypatch, capsys
):
    fact = '青い観測灯 station beacon\tcausal calibration 😀'
    assert n3m._save_text("claude", fact, "old-turn", "old-chat") == (1, 0)

    def missing_exchange(*args):
        raise sqlite3.OperationalError("supplementary read failed")

    monkeypatch.setattr(p, "get_memories_by_turn_id", missing_exchange)
    with TestClient(n3m.create_app(), base_url="http://127.0.0.1:18526") as client:
        def post(path, body, **kwargs):
            response = client.post(path, json=body)
            response.raise_for_status()
            return response.json()

        monkeypatch.setattr(n3m, "_post", post)
        monkeypatch.setattr(n3m, "_use_server", lambda: True)
        monkeypatch.setattr(codex_entry._sys, "stdin", io.StringIO(json.dumps({
            "session_id": "new-chat", "turn_id": "new-turn", "prompt": fact
        })))
        assert codex_entry.prompt_main() == 0

    output = json.loads(capsys.readouterr().out)
    assert f"[claude] {fact}" in output["hookSpecificOutput"]["additionalContext"]
    assert conn.execute("SELECT content FROM memories WHERE turn_id='new-turn'").fetchone()[0] == "[user] " + fact


@pytest.mark.parametrize("response", [{"message": "invalid"}, {"results": [{}]}])
def test_bad_search_response_surfaces_error_and_does_not_discard_prompt(conn, monkeypatch, response):
    monkeypatch.setattr(n3m, "_use_server", lambda: True)
    monkeypatch.setattr(n3m, "_post", lambda *args, **kwargs: response)
    result = codex_entry.handle("UserPromptSubmit", json.dumps({
        "session_id": "chat", "turn_id": "turn", "prompt": "Save this normally"
    }))
    assert "memory search unavailable" in result["hookSpecificOutput"]["additionalContext"]
    assert conn.execute("SELECT content FROM memories").fetchone()[0] == "[user] Save this normally"


def test_valid_hits_survive_bad_supplement_and_unexpected_save_failure(monkeypatch):
    row = {"score": 0.7, "timestamp": "2026-11-25T00:00:00+00:00", "content": "prior evidence"}
    monkeypatch.setattr(n3m, "_use_server", lambda: True)
    monkeypatch.setattr(n3m, "_post", lambda *args, **kwargs: {
        "results": [row], "pairs": {"old": [{}]}, "pairs_omitted": {}
    })

    def failed_save(*args):
        raise OSError("disk failure")

    monkeypatch.setattr(n3m, "_save_text", failed_save)
    result = codex_entry.handle("UserPromptSubmit", json.dumps({
        "session_id": "chat", "turn_id": "turn", "prompt": "Find the evidence"
    }))
    assert "prior evidence" in result["hookSpecificOutput"]["additionalContext"]
    assert "Supplementary exchanges could not be displayed" in result["hookSpecificOutput"]["additionalContext"]
    assert "could not save" in result["systemMessage"]


def test_connected_omission_preserves_turn_id_without_claiming_a_local_copy():
    context = p.render_memory_context("query", [], pairs_omitted={"remote-turn": 2}, connected=True)
    assert "remote-turn" in context and "2 more chunk(s)" in context
    assert "stored on the connected server" in context
    assert "--show-turn" not in context
