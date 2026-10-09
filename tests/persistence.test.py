"""Tests for the paired dotfiles helper; pass its source path as argv[1]."""
import json
import os
from pathlib import Path
import runpy
import sys
import unittest
from unittest.mock import patch

source = Path(sys.argv.pop(1)) if len(sys.argv) > 1 else Path.home() / '.local/bin/tmux-persist'
persist = runpy.run_path(str(source))
rewrite = persist['rewrite_snapshot']


def pane(name, command='node', full=':node pi.js'):
    return '\t'.join(['pane', name, '0', '1', ':*', '0', ':title', ':/tmp', '1', command, full])


def window(name):
    return '\t'.join(['window', name, '0', '1', ':*', 'test-layout', '1'])


class PersistenceTests(unittest.TestCase):
    def test_numeric_names_only_are_disposable(self):
        names = ['0', '123', 'project', '12-tools', '١٢', '001']
        result = rewrite('\n'.join(pane(name) for name in names), {})
        saved = [line.split('\t')[1] for line in result.splitlines() if line.startswith('pane\t')]
        self.assertEqual(saved, ['project', '12-tools', '١٢'])

    def test_group_rebases_disposable_original(self):
        text = '\n'.join([pane('0'), window('0'), 'grouped_session\tproject\t0', 'grouped_session\t42\t0', 'grouped_session\talias\t0', 'state\t0\t42'])
        result = rewrite(text, {})
        self.assertIn('pane\tproject\t', result)
        self.assertIn('window\tproject\t', result)
        self.assertIn('grouped_session\talias\tproject', result)
        self.assertNotIn('grouped_session\t42', result)
        self.assertNotIn('pane\t0\t', result)
        self.assertIn('state\tproject\tproject', result)

    def test_every_unverified_process_is_scrubbed(self):
        result = rewrite(pane('project', 'ssh', ':ssh secret-host'), {})
        row = result.splitlines()[0].split('\t')
        self.assertEqual(row[9:], ['shell', ':'])
        self.assertNotIn('ssh', result)

    def test_pi_payload_roundtrips_paths_with_spaces(self):
        data = {'kind': 'pi', 'sessionFile': '/tmp/session with spaces.jsonl'}
        result = rewrite(pane('project'), {('project', '0', '0'): data})
        row = result.splitlines()[0].split('\t')
        self.assertEqual(row[9], 'tmux-persist')
        self.assertTrue(row[10].startswith(':tmux-persist resume '))
        payload = row[10].split(' ')[-1]
        self.assertEqual(json.loads(persist['base64'].urlsafe_b64decode(payload)), data)

    def test_an_all_disposable_snapshot_contains_no_restore_state(self):
        self.assertEqual(rewrite(pane('0') + '\nstate\t0\t0', {}), '')

    def test_reused_pid_is_rejected(self):
        data = {'pid': os.getpid(), 'start': 'definitely-not-the-start-time'}
        self.assertFalse(persist['active_process'](data, os.getpid()))

    def test_current_process_has_a_stable_identity(self):
        info = persist['process_info'](os.getpid())
        self.assertIsNotNone(info)
        self.assertGreater(int(info['start']), 0)
        self.assertTrue(persist['active_process']({'pid': os.getpid(), 'start': info['start']}, os.getpid()))

    def test_resume_uses_exact_file_and_original_profile_not_continue(self):
        data = {'version': 1, 'kind': 'pi', 'sessionFile': '/saved/exact session.jsonl',
                'cwd': '/project', 'executable': '/usr/bin/node', 'entrypoint': '/pi/cli.js',
                'environment': {'PI_CODING_AGENT_DIR': '/profile', 'API_KEY': 'not-allowed'}}
        with patch.object(Path, 'is_file', return_value=True), patch('os.chdir') as cd, patch('os.execvpe') as execute:
            persist['resume'](persist['encode'](data))
        cd.assert_called_once_with('/project')
        argv = execute.call_args.args[1]
        env = execute.call_args.args[2]
        self.assertEqual(argv, ['/usr/bin/node', '/pi/cli.js', '--session', '/saved/exact session.jsonl'])
        self.assertEqual(env['PI_CODING_AGENT_DIR'], '/profile')
        self.assertNotEqual(env.get('API_KEY'), 'not-allowed')
        self.assertNotIn('--continue', argv)


unittest.main()
