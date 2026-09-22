import { randomUUID } from "node:crypto";
import { win32 } from "node:path";
import { sendEvent } from "./transport.js";

/** @param {import('@earendil-works/pi-coding-agent').ExtensionAPI} pi */
export default function extension(pi) {
  installExtension(pi);
}

// Dependencies are injectable so lifecycle/privacy tests do not create toasts.
export function installExtension(pi, {
  platform = process.platform,
  env = process.env,
  send = sendEvent,
  uuid = () => randomUUID().replaceAll("-", ""),
} = {}) {
  const helper = env.LOCALAPPDATA
    ? win32.join(env.LOCALAPPDATA, "CodexWinNotify", "app", "CodexWinNotify.exe")
    : undefined;
  const supported = platform === "win32" && !!env.WT_SESSION && !!helper;
  const ids = new Map();
  const controller = new AbortController();
  let queue = Promise.resolve();
  let pending = 0;
  let closed = false;
  let warned = false;
  let running = false;
  let stopReason;

  function warn(ctx, text) {
    if (closed || warned || ctx.mode !== "tui") return;
    warned = true;
    ctx.ui.notify(text, "warning");
  }

  function enqueue(kind, ctx) {
    if (closed || ctx.mode !== "tui") return Promise.resolve(false);
    if (!supported) {
      warn(ctx, "Pi Windows 通知仅支持 Windows 原生 Pi + Windows Terminal（不支持 WSL/RPC）。");
      return Promise.resolve(false);
    }
    // Bound memory during rapid UI/tool activity. Never block a prompt on I/O.
    if (pending >= 16) return Promise.resolve(false);
    const session = ctx.sessionManager.getSessionId();
    if (!ids.has(session)) ids.set(session, uuid());
    const event = {
      Id: ids.get(session),
      Kind: kind,
      Cwd: win32.basename(ctx.cwd).slice(0, 256),
      Key: uuid(),
      ThreadName: (pi.getSessionName() || "").slice(0, 256),
      Client: "Pi",
    };
    // Only window/session metadata; never include prompt, command or response text.
    pending++;
    const task = queue.then(async () => {
      if (closed) return false;
      try {
        await send(helper, event, controller.signal);
        return true;
      } catch {
        warn(ctx, "Pi Windows 通知发送失败。请运行 install-pi.ps1 更新助手，并检查 %LOCALAPPDATA%\\CodexWinNotify\\helper.log。");
        return false;
      }
    }).finally(() => { pending--; });
    queue = task.catch(() => false);
    return task;
  }

  pi.on("session_start", (_event, ctx) => {
    // Also handles /reload; no child processes are started in the factory.
    running = false;
    stopReason = undefined;
    void enqueue("register", ctx);
  });
  pi.on("agent_start", () => {
    running = true;
    stopReason = undefined;
  });
  pi.on("message_end", (event) => {
    if (event.message.role === "assistant") stopReason = event.message.stopReason;
  });
  pi.on("agent_before_settle", (event) => {
    // Covers cancellation/failure before an assistant message is produced.
    // Observe only: do not return entries or request a continuation.
    stopReason = event.outcome === "completed" ? "stop" : event.outcome;
  });
  // agent_end can precede retries, compaction and queued follow-ups.
  pi.on("agent_settled", (_event, ctx) => {
    if (!running) return;
    running = false;
    if (stopReason === "aborted") return;
    void enqueue(stopReason === "error" ? "error" : "complete", ctx);
  });
  pi.on("ui_prompt_start", (_event, ctx) => {
    // UI prompt titles can contain questions/commands. Deliberately ignore them.
    void enqueue("question", ctx);
  });
  pi.on("session_compact", (_event, ctx) => {
    void enqueue("compact", ctx);
  });
  pi.on("session_shutdown", () => {
    closed = true;
    controller.abort();
    // Keep persisted window bindings: delayed notification clicks should still
    // reach the original window, even after a reload or session switch.
  });
  pi.registerCommand("cli-notify-test", {
    description: "发送 Windows 测试通知；点击应返回当前终端（不调用模型）",
    handler: async (_args, ctx) => {
      if (await enqueue("test", ctx)) {
        ctx.ui.notify("测试通知已发送，请切换到其他窗口后点击通知验证。", "info");
      }
    },
  });
}
