"""One-time migration of the legacy init tests to the Codex contract."""
from pathlib import Path

path = Path('tests/test_regressions.py')
text = path.read_text(encoding='utf-8')
start = text.index('class TestInit:\n')
end = text.index('    def test_resolve_finds_scripts_folder', start)
replacement = '''class TestInit:
    @pytest.fixture
    def settings(self, tmp_path, monkeypatch):
        path = tmp_path / 'codex' / 'hooks.json'
        path.parent.mkdir()
        monkeypatch.setenv('N3MC_CODEX_HOOKS_PATH', str(path))
        monkeypatch.setattr(n3memory.sys, 'executable', 'C:/fake/Python/python.exe')
        return path

    def own_cmds(self, data, event):
        return [h['command'] for e in data['hooks'][event] for h in e['hooks']
                if 'n3memorycore.codex_entry' in h['command']]

    def test_pro_hook_kept_and_trust_reminder(self, settings, capsys):
        settings.write_text(json.dumps({'hooks': {'UserPromptSubmit': [
            {'hooks': [{'type': 'command', 'command': PRO_HOOK}]}]}}), encoding='utf-8')
        assert n3memory.cmd_init() == 0
        data = json.loads(settings.read_text(encoding='utf-8'))
        cmds = [h['command'] for e in data['hooks']['UserPromptSubmit'] for h in e['hooks']]
        assert PRO_HOOK in cmds
        assert self.own_cmds(data, 'UserPromptSubmit') == [
            'C:/fake/Python/python.exe -m n3memorycore.codex_entry --prompt']
        assert 'Review and trust both hooks' in capsys.readouterr().out

    def test_own_forms_replaced_not_duplicated(self, settings):
        old = ['C:/old/python.exe -m n3memorycore.codex_entry --prompt',
               'python -m n3memorycore.codex_entry --prompt']
        settings.write_text(json.dumps({'hooks': {
            'UserPromptSubmit': [{'hooks': [{'type': 'command', 'command': c}]} for c in old],
            'Stop': [{'hooks': [{'type': 'command',
                                 'command': 'python -m n3memorycore.codex_entry --stop'}]}],
        }}), encoding='utf-8')
        assert n3memory.cmd_init() == 0
        data = json.loads(settings.read_text(encoding='utf-8'))
        assert self.own_cmds(data, 'UserPromptSubmit') == [
            'C:/fake/Python/python.exe -m n3memorycore.codex_entry --prompt']
        assert self.own_cmds(data, 'Stop') == [
            'C:/fake/Python/python.exe -m n3memorycore.codex_entry --stop']
        assert len(data['hooks']['UserPromptSubmit']) == 1

    def test_rerun_writes_nothing(self, settings, capsys):
        settings.write_text('{"custom": "x"}', encoding='utf-8')
        assert n3memory.cmd_init() == 0
        first = settings.read_bytes()
        backups = sorted(p for p in os.listdir(settings.parent) if '.bak-n3mc-' in p)
        assert len(backups) == 1
        assert (settings.parent / backups[0]).read_text(encoding='utf-8') == '{"custom": "x"}'
        capsys.readouterr()
        assert n3memory.cmd_init() == 0
        assert settings.read_bytes() == first
        assert sorted(p for p in os.listdir(settings.parent) if '.bak-n3mc-' in p) == backups
        assert 'Already registered' in capsys.readouterr().out

    def test_invalid_settings_untouched_exit_1(self, settings):
        for invalid in ('{"hooks": [,]}', '{"hooks": {"Stop": "invalid"}}'):
            settings.write_text(invalid, encoding='utf-8')
            assert n3memory.cmd_init() == 1
            assert settings.read_text(encoding='utf-8') == invalid
        assert not [p for p in os.listdir(settings.parent) if '.bak-n3mc-' in p]

    def test_main_exit_status_1(self, settings, monkeypatch):
        settings.write_text('not json', encoding='utf-8')
        monkeypatch.setattr('sys.argv', ['n3mc', '--init'])
        with pytest.raises(SystemExit) as ei:
            n3memory.main()
        assert ei.value.code == 1

    def test_other_configuration_is_preserved(self, settings):
        original = {'permissions': {'allow': ['custom'], 'deny': ['another']}}
        settings.write_text(json.dumps(original), encoding='utf-8')
        assert n3memory.cmd_init() == 0
        assert json.loads(settings.read_text(encoding='utf-8'))['permissions'] == original['permissions']

    def test_codex_init_and_stop_do_not_modify_claude_files(self, settings, tmp_path, monkeypatch):
        claude_dir = stop_in(tmp_path, monkeypatch)
        rule = claude_dir / 'rules' / 'n3mc-behavior.md'
        rule.write_text(OLD_TEMPLATE_V1, encoding='utf-8')
        md = claude_dir / 'CLAUDE.md'
        md.write_text('@' + n3memory.CONTEXT_FILE, encoding='utf-8')
        before = {p: p.read_bytes() for p in (rule, md)}
        assert n3memory.cmd_init() == 0
        n3memory.cmd_stop({})
        assert {p: p.read_bytes() for p in (rule, md)} == before

'''
path.write_text(text[:start] + replacement + text[end:], encoding='utf-8')
