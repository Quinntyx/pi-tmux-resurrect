#!/usr/bin/env python3
"""Isolated real tmux/Pi/nvim restart test. Never touches the user's tmux server.
Usage: python3 integration.py CHEZMOI_SOURCE
Requires the paired helper and tmux-resurrect to have been applied.
"""
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import uuid

source = Path(sys.argv[1])
plugin = Path(__file__).resolve().parents[1]
real_home = Path.home()
root = Path(tempfile.mkdtemp(prefix='pi-tmux-persistence-'))
socket = str(root / 'tmux.sock')
env = os.environ.copy()
for key in ('TMUX', 'TMUX_PANE', 'PI_CODING_AGENT_DIR', 'PPI_PI_DIR', 'PPI_PROFILE', 'PPI_PROFILE_DIR'):
    env.pop(key, None)
env.update(HOME=str(root), XDG_STATE_HOME=str(root / '.local/state'), XDG_CONFIG_HOME=str(root / '.config'),
           PI_CODING_AGENT_DIR=str(root / 'pi'), PPI_PI_DIR=str(root / 'pi'), PPI_PROFILE='persistence-test',
           PI_OFFLINE='1', PATH=str(root / '.local/bin') + ':' + env['PATH'])
(root / '.local/bin').mkdir(parents=True)
shutil.copy2(real_home / '.local/bin/tmux-persist', root / '.local/bin/tmux-persist')
shutil.copytree(real_home / '.local/share/tmux/plugins/tmux-resurrect', root / '.local/share/tmux/plugins/tmux-resurrect', symlinks=True)
(root / '.config/nvim').mkdir(parents=True)
(root / '.config/nvim/init.lua').write_text('dofile(' + json.dumps(str(source / 'dot_config/nvim/lua/tmux-persistence.lua')) + ')\n')
(root / 'pi').mkdir()
(root / 'pi/settings.json').write_text(json.dumps({'packages': [str(plugin)]}))
config = root / 'tmux.conf'
config.write_text('set -g status off\nset -g default-shell /bin/bash\n' + (source / 'dot_config/tmux/persistence.conf').read_text())


def run(args, *, check=True, timeout=10, local_env=None):
    result = subprocess.run(args, env=local_env or env, text=True, capture_output=True, timeout=timeout)
    if check and result.returncode:
        raise RuntimeError(str(args) + ': ' + result.stderr)
    return result.stdout.rstrip('\n')


def tmux(*args, check=True):
    return run(['tmux', '-S', socket, *args], check=check)


def wait_for(callback, description, timeout=20):
    until = time.monotonic() + timeout
    last = None
    while time.monotonic() < until:
        try:
            value = callback()
            if value:
                return value
        except (ValueError, KeyError, RuntimeError) as error:
            last = error
        time.sleep(0.2)
    raise RuntimeError('Timed out: ' + description + ('; ' + str(last) if last else ''))


def option(pane, key):
    value = tmux('show-option', '-p', '-v', '-t', pane, key, check=False)
    return json.loads(value) if value else None


def start_server(name):
    tmux('-f', str(config), 'new-session', '-d', '-s', name, '-c', str(root))
    wait_for(lambda: tmux('show-option', '-g', '-v', '@tmux-persist-ready', check=False), 'startup restoration')


def helper(action):
    local = env.copy()
    local['TMUX'] = socket + ',' + tmux('display-message', '-p', '#{pid}') + ',0'
    return run([str(root / '.local/bin/tmux-persist'), action], local_env=local, timeout=65)


try:
    print('Test artifacts:', root, flush=True)
    start_server('project')
    editor_file = root / 'notes with spaces.txt'
    editor_file.write_text('A persistent editor buffer.\n')
    tmux('send-keys', '-t', 'project:0.0', shlex.join(['nvim', str(editor_file)]), 'Enter')
    editor = wait_for(lambda: option('project:0.0', '@nvim-resurrect'), 'nvim session metadata')
    sessions = []
    pi_metadata = []
    for index in (1, 2):
        session = root / f'exact pi session {index}.jsonl'
        session.write_text(json.dumps({'type': 'session', 'version': 3, 'id': str(uuid.uuid4()),
                                      'timestamp': '2026-10-09T00:00:00.000Z', 'cwd': str(root)}) + '\n')
        sessions.append(str(session))
        tmux('new-window', '-t', 'project:' + str(index), '-c', str(root))
        tmux('send-keys', '-t', 'project:' + str(index), shlex.join(['pi', '--no-approve', '--session', str(session)]), 'Enter')
        data = wait_for(lambda: option('project:' + str(index) + '.0', '@pi-resurrect'), 'Pi exact-session metadata')
        assert data['sessionFile'] == str(session), data
        pi_metadata.append(data)
    tmux('new-window', '-t', 'project:3', '-c', str(root), 'sleep 600')
    tmux('new-session', '-d', '-s', '123', 'sleep 600')
    tmux('new-session', '-d', '-s', '88', '-t', 'project')
    tmux('new-session', '-d', '-s', '77', '-c', str(root))
    tmux('new-session', '-d', '-s', 'grouped-named', '-t', '77')
    print('Real Pi and nvim advertised their session files; saving with status off.', flush=True)
    helper('save')
    snapshot = root / '.local/state/tmux/resurrect/last'
    original = snapshot.read_text()
    lines = [line.split('\t') for line in original.splitlines()]
    assert all(not row[1].isdigit() for row in lines if row[0] in ('pane', 'window', 'grouped_session')), original
    for session in sessions:
        decoded = []
        for row in lines:
            if row[0] == 'pane' and row[9] == 'tmux-persist':
                import base64
                decoded.append(json.loads(base64.urlsafe_b64decode(row[10].split()[-1])))
        assert any(data['sessionFile'] == session for data in decoded), (session, original)
    assert any(data['kind'] == 'nvim' for data in decoded), original
    assert 'sleep 600' not in original, original
    old_server = tmux('display-message', '-p', '#{pid}')
    tmux('kill-server')
    wait_for(lambda: not Path('/proc/' + old_server).exists(), 'old server death', timeout=5)
    start_server('0')
    names = set(tmux('list-sessions', '-F', '#{session_name}').splitlines())
    assert {'project', 'grouped-named'} <= names, names
    assert not {'123', '77', '88'} & names, names
    for index, session in enumerate(sessions, start=1):
        data = wait_for(lambda: option('project:' + str(index) + '.0', '@pi-resurrect'), 'restored Pi')
        assert data['sessionFile'] == session, data
        assert data['pid'] != pi_metadata[index - 1]['pid'], data
        assert data['environment']['PI_CODING_AGENT_DIR'] == str(root / 'pi'), data
        # Pi sets process.title='pi', which intentionally erases /proc/cmdline.
        # Its session manager advertising this path proves the conversation reopened.
    restored_editor = wait_for(lambda: option('project:0.0', '@nvim-resurrect'), 'restored nvim')
    assert restored_editor['pid'] != editor['pid'], restored_editor
    assert editor_file.name in Path(restored_editor['sessionFile']).read_text().replace('\\ ', ' '), restored_editor
    assert tmux('display-message', '-p', '-t', 'project:3.0', '#{pane_current_command}') != 'sleep'
    # Source reload must not recreate a named session the user deliberately closed.
    tmux('kill-session', '-t', 'grouped-named')
    tmux('source-file', str(config))
    time.sleep(1)
    assert 'grouped-named' not in tmux('list-sessions', '-F', '#{session_name}').splitlines()
    # Stale process metadata must not be saved after the Pi process is gone.
    tmux('send-keys', '-t', 'project:1.0', 'C-c')
    tmux('send-keys', '-t', 'project:1.0', 'C-c')
    wait_for(lambda: tmux('display-message', '-p', '-t', 'project:1.0', '#{pane_current_command}') in ('bash', 'zsh'), 'Pi shutdown')
    tmux('set-option', '-p', '-t', 'project:1.0', '@pi-resurrect', json.dumps(pi_metadata[0]))
    helper('save')
    rows = [line.split('\t') for line in snapshot.read_text().splitlines()]
    closed = next(row for row in rows if row[0] == 'pane' and row[1:3] == ['project', '1'])
    assert closed[9:] == ['shell', ':'], closed
    assert tmux('show-option', '-g', '-v', 'status') == 'off'
    print('PASS: two exact Pi sessions in one cwd, profile environment, nvim buffer, named/grouped filtering, status-off saves, non-Pi/nvim scrub, safe reload, stale metadata.', flush=True)
finally:
    tmux('kill-server', check=False)
