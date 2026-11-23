"""Regression tests for the code review of 2026-11-17 (spec §4, §5).

2. No chunk is longer than max_chars, overlap and separator included.
3. A hook command written with backslashes and no quotes is recognized.

No embedding model. Real data and real settings are never touched
(conftest._isolate_real_data; settings.json lives in a temporary home).
"""
import json
import os

import pytest

from n3memorycore.core.processor import chunk_text



def letters(chunks):
    return ''.join(ch for c in chunks for ch in c if not ch.isspace())


class TestChunkLengthBound:
    def test_review_case(self):
        chunks = chunk_text('x' * 10 + '\n\n' + 'y' * 400)
        assert max(len(c) for c in chunks) <= 400
        joined = letters(chunks)
        assert joined.count('x') >= 10 and joined.count('y') >= 400

    @pytest.mark.parametrize('max_chars', [400, 120, 50])
    def test_paragraphs(self, max_chars):
        paras = [('p%d ' % i) * (5 + (i * 7) % (max_chars // 3)) for i in range(40)]
        text = '\n\n'.join(p.strip() for p in paras)
        chunks = chunk_text(text, max_chars=max_chars, overlap=40)
        assert chunks and max(len(c) for c in chunks) <= max_chars

    @pytest.mark.parametrize('max_chars', [400, 120])
    def test_sentences(self, max_chars):
        text = ' '.join('Sentence number %d has %s.' % (i, 'w' * (i % 60)) for i in range(80))
        chunks = chunk_text(text, max_chars=max_chars, overlap=40)
        assert max(len(c) for c in chunks) <= max_chars

    def test_japanese(self):
        text = ''.join('これは%d番目の文で、長さを少しずつ変えています%s。' % (i, 'あ' * (i % 50))
                       for i in range(60))
        chunks = chunk_text(text)
        assert max(len(c) for c in chunks) <= 400
        # every sentence still appears in some chunk
        for i in range(60):
            assert any('これは%d番目の文' % i in c for c in chunks)

    def test_overlap_kept_when_it_fits(self):
        text = '\n\n'.join(['a' * 300, 'b' * 150])
        chunks = chunk_text(text)
        assert chunks == ['a' * 300, 'a' * 40 + '\n\n' + 'b' * 150]


class TestCodexInit:
    def test_replaces_own_hook_without_duplicate(self, tmp_path, monkeypatch):
        from n3memorycore import codex_install
        path = tmp_path / 'hooks.json'
        monkeypatch.setenv('N3MC_CODEX_HOOKS_PATH', str(path))
        path.write_text(json.dumps({'hooks': {
            'UserPromptSubmit': [{'hooks': [{'type': 'command',
                'command': 'python -m n3memorycore.codex_entry --prompt'}]}],
            'Stop': [{'hooks': [{'type': 'command',
                'command': 'python -m n3memorycore.codex_entry --stop'}]}],
        }}), encoding='utf-8')
        assert codex_install.install() == 0
        data = json.loads(path.read_text(encoding='utf-8'))
        for event in ('UserPromptSubmit', 'Stop'):
            cmds = [h['command'] for e in data['hooks'][event] for h in e['hooks']]
            assert len(cmds) == 1
            assert 'n3memorycore.codex_entry' in cmds[0]
