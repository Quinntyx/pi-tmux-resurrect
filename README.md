# pi-tmux-resurrect

Restore the **exact Pi conversation** in each tmux pane, not whichever
conversation happens to be the latest in that directory.

## Install

Add `git:git.quinntyx.dev/quinntyx/pi-tmux-resurrect@main` to the `packages`
array in each Pi profile's `settings.json`, then reload Pi. GitHub is a
server-side mirror; the forge is canonical.

## How it works

The extension publishes JSON in the pane-local `@pi-resurrect` tmux option:

- absolute session JSONL path and working directory;
- Pi's Node executable and CLI entrypoint;
- profile/config-directory environment (a fixed non-secret allowlist);
- process PID and Linux process start time, to reject stale/reused PIDs.

It refreshes on session startup/reload/replacement, conversation messages,
metadata changes, and a ten-second fallback interval. It removes its own
metadata on shutdown. Non-TTY Pi subprocesses cannot overwrite their parent's
metadata. Ephemeral `--no-session` conversations cannot be restored.

A **save hook is required**: tmux-resurrect does not save custom pane options
itself. The paired implementation lives in
[Quinntyx's dotfiles](https://git.quinntyx.dev/quinntyx/dots):
`private_dot_local/bin/executable_tmux-persist` and
`dot_config/tmux/persistence.conf`. It verifies the process is still alive,
is in the pane's process tree, and belongs to the foreground process group;
then serializes the metadata into the resurrect snapshot. Restoring executes
the same installed Pi CLI with `--session <absolute-session-file>` and the
original profile environment. Other process commands are never replayed.

The paired setup also preserves nvim sessions, excludes purely numeric tmux
session names (including grouped-session aliases), and uses a systemd user
timer rather than continuum/status-line redraws. Snapshots, editor sessions,
process IDs, and credentials remain runtime state, never Git content.

## Limits

Linux and tmux are required. This is reconstruction, not process checkpointing:
model calls, Python kernels, extension memory, and other live state are lost.
Only durable sessions with an existing JSONL file can be restored. Existing
Pi instances must reload once after installation to publish their metadata.

## Tests

Run `npm test` using Node 22.18+ (built-in TypeScript type stripping).
There are no runtime npm dependencies. The extension uses Pi's supported API.

Paired dotfiles tests (after applying the helper and resurrect archive):

```sh
python3 tests/persistence.test.py ~/.local/bin/tmux-persist
python3 tests/integration.py ~/.local/share/chezmoi
```

The integration test starts its own tmux socket and temporary HOME, launches real
Pi and nvim processes, kills only that isolated server, and checks exact-session
restoration, profile preservation, numeric/group filtering, status-off saving,
stale-process rejection, and config reload safety. Test artifacts remain in `/tmp`.
