import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { readFileSync } from "node:fs";
import { spawnSync } from "node:child_process";

export const PANE_OPTION = "@pi-resurrect";
export const ENV_KEYS = [
  "PI_CODING_AGENT_DIR", "PI_CODING_AGENT_SESSION_DIR",
  "PPI_PI_DIR", "PPI_PROFILE", "PPI_PROFILE_DIR",
] as const;

export function processStart(pid: number): string | undefined {
  try {
    const stat = readFileSync(`/proc/${pid}/stat`, "utf8");
    return stat.slice(stat.lastIndexOf(")") + 2).split(" ")[19];
  } catch {
    return undefined;
  }
}

export function metadata(ctx: Pick<ExtensionContext, "cwd" | "sessionManager">) {
  const sessionFile = ctx.sessionManager.getSessionFile();
  if (!sessionFile) return undefined; // --no-session cannot be restored.
  const environment: Record<string, string> = {};
  for (const key of ENV_KEYS) {
    if (process.env[key]) environment[key] = process.env[key]!;
  }
  return {
    version: 1, kind: "pi", pid: process.pid, start: processStart(process.pid),
    sessionFile, cwd: ctx.cwd, executable: process.execPath,
    entrypoint: process.argv[1], environment,
  };
}

export default function tmuxResurrect(pi: ExtensionAPI) {
  const socket = process.env.TMUX?.split(",")[0];
  const pane = process.env.TMUX_PANE;
  // Non-interactive Pi subprocesses inherit TMUX too; they must not overwrite
  // the metadata belonging to the interactive Pi which owns this terminal.
  if (!socket || !pane || !process.stdin.isTTY || !process.stdout.isTTY) return;

  let timer: ReturnType<typeof setInterval> | undefined;
  let last = "";
  const tmux = (args: string[]) => spawnSync("tmux", ["-S", socket, ...args], {
    encoding: "utf8", stdio: ["ignore", "pipe", "ignore"], timeout: 2000,
  });
  const publish = (ctx: ExtensionContext) => {
    const data = metadata(ctx);
    if (!data?.start) return;
    const value = JSON.stringify(data);
    if (value === last) return;
    if (tmux(["set-option", "-p", "-t", pane, PANE_OPTION, value]).status === 0) last = value;
  };
  const clear = () => {
    if (timer) clearInterval(timer);
    timer = undefined;
    const existing = tmux(["show-options", "-p", "-v", "-t", pane, PANE_OPTION]);
    try {
      if (JSON.parse(existing.stdout).pid === process.pid) {
        tmux(["set-option", "-p", "-u", "-t", pane, PANE_OPTION]);
      }
    } catch { /* Pane disappeared, or another Pi owns it now. */ }
    last = "";
  };

  pi.on("session_start", (_event, ctx) => {
    clear();
    publish(ctx);
    timer = setInterval(() => publish(ctx), 10_000);
    timer.unref();
  });
  // Refresh once the first conversation message has made the session durable.
  pi.on("message_end", (_event, ctx) => publish(ctx));
  pi.on("session_info_changed", (_event, ctx) => publish(ctx));
  pi.on("session_shutdown", clear);
}
