import assert from 'node:assert/strict';
import test from 'node:test';
import extension, { metadata, processStart, PANE_OPTION, ENV_KEYS } from '../extensions/index.ts';

const ctx = (file) => ({ cwd: '/tmp/project with spaces', sessionManager: { getSessionFile: () => file } });

test('records the exact session file, cwd, installed CLI and process identity', () => {
  const data = metadata(ctx('/tmp/session with spaces.jsonl'));
  assert.equal(data.kind, 'pi');
  assert.equal(data.sessionFile, '/tmp/session with spaces.jsonl');
  assert.equal(data.cwd, '/tmp/project with spaces');
  assert.equal(data.pid, process.pid);
  assert.equal(data.start, processStart(process.pid));
  assert.equal(data.executable, process.execPath);
  assert.equal(data.entrypoint, process.argv[1]);
});

test('a session replacement captures the new path, not the original argv', () => {
  assert.notEqual(metadata(ctx('/tmp/first.jsonl')).sessionFile, metadata(ctx('/tmp/second.jsonl')).sessionFile);
});

test('ephemeral sessions are not advertised', () => {
  assert.equal(metadata(ctx(undefined)), undefined);
});

test('missing processes are harmless', () => {
  assert.equal(processStart(2147483647), undefined);
});

test('the environment allowlist contains config selectors, never credentials', () => {
  assert.equal(PANE_OPTION, '@pi-resurrect');
  assert.ok(ENV_KEYS.includes('PI_CODING_AGENT_DIR'));
  assert.ok(ENV_KEYS.every(key => !/TOKEN|SECRET|API_KEY|PASSWORD/.test(key)));
  assert.ok(Object.keys(metadata(ctx('/tmp/session.jsonl')).environment).every(key => ENV_KEYS.includes(key)));
});

test('non-TTY Pi subprocesses do not register handlers or timers', () => {
  let registrations = 0;
  extension({ on() { registrations++; } });
  assert.equal(registrations, 0);
});
