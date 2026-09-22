import test from "node:test";
import assert from "node:assert/strict";
import { installExtension } from "../../pi/cli-notify.js";

const tick = () => new Promise(resolve => setImmediate(resolve));
function harness(options = {}) {
  const handlers = new Map(), commands = new Map(), sent = [], notices = [];
  let name = "中文会话", session = "session-1";
  const pi = {
    on: (name, handler) => handlers.set(name, handler),
    registerCommand: (name, command) => commands.set(name, command),
    getSessionName: () => name,
  };
  const ctx = {
    mode: "tui", cwd: "C:\\中文 空格 & test\\项目",
    sessionManager: { getSessionId: () => session },
    ui: { notify: (...args) => notices.push(args) },
  };
  installExtension(pi, {
    platform: "win32", env: { LOCALAPPDATA: "C:\\用户 空格", WT_SESSION: "terminal" },
    send: async (helper, event) => { sent.push({ helper, ...event }); },
    ...options,
  });
  return {
    handlers, ctx, sent, notices,
    emit: async (name, event = {}) => { await handlers.get(name)?.(event, ctx); await tick(); },
    test: () => commands.get("cli-notify-test").handler("", ctx),
    rename: value => { name = value; },
    switchSession: value => { session = value; },
  };
}

test("factory is inert; start registers metadata; test is model-free", async () => {
  const h = harness();
  assert.equal(h.sent.length, 0);
  await h.emit("session_start");
  await h.test();
  assert.deepEqual(h.sent.map(e => e.Kind), ["register", "test"]);
  assert.equal(h.sent[0].Id, h.sent[1].Id);
  assert.notEqual(h.sent[0].Key, h.sent[1].Key);
  assert.match(h.sent[0].Id, /^[a-f0-9]{32}$/);
  assert.equal(h.sent[0].Cwd, "项目");
  assert.equal(h.sent[0].ThreadName, "中文会话");
  assert.equal(h.sent[0].Client, "Pi");
  assert.equal(h.sent[0].helper, "C:\\用户 空格\\CliNotify\\app\\CliNotify.exe");
});

test("session start registers silently for every reason", async () => {
  for (const reason of ["startup", "reload", "new", "resume", "fork"]) {
    const h = harness();
    await h.emit("session_start", { reason });
    assert.deepEqual(h.notices, []);
    assert.deepEqual(h.sent.map(e => e.Kind), ["register"]);
  }
});

test("session start stays silent outside TUI", async () => {
  for (const mode of ["rpc", "json", "print"]) {
    const h = harness();
    h.ctx.mode = mode;
    await h.emit("session_start", { reason: "startup" });
    assert.deepEqual(h.notices, []);
    assert.deepEqual(h.sent, []);
  }
});

test("only final settlement notifies, once; retries replace intermediate errors", async () => {
  const h = harness();
  await h.emit("agent_start");
  await h.emit("message_end", { message: { role: "assistant", stopReason: "error", content: "PRIVATE" } });
  await h.emit("agent_end");
  assert.equal(h.sent.length, 0);
  await h.emit("agent_start");
  await h.emit("message_end", { message: { role: "assistant", stopReason: "stop", content: "PRIVATE" } });
  await h.emit("agent_settled");
  await h.emit("agent_settled");
  assert.deepEqual(h.sent.map(e => e.Kind), ["complete"]);
  assert.ok(!JSON.stringify(h.sent).includes("PRIVATE"));
});

test("error versus cancellation", async () => {
  const h = harness();
  for (const stopReason of ["error", "aborted"]) {
    await h.emit("agent_start");
    await h.emit("message_end", { message: { role: "assistant", stopReason } });
    await h.emit("agent_settled");
  }
  assert.deepEqual(h.sent.map(e => e.Kind), ["error"]);
});

test("pre-settlement outcome handles cancellation and errors without assistant messages", async () => {
  const h = harness();
  for (const outcome of ["aborted", "error", "completed"]) {
    await h.emit("agent_start");
    await h.emit("agent_before_settle", { outcome });
    await h.emit("agent_settled");
  }
  assert.deepEqual(h.sent.map(e => e.Kind), ["error", "complete"]);
});

test("UI and compaction payloads stay private; names refreshed; IDs isolate sessions and instances", async () => {
  const h = harness(), other = harness();
  await h.emit("ui_prompt_start", { title: "PRIVATE command/question" });
  h.rename("新名称");
  await h.emit("session_compact", { summary: "PRIVATE summary" });
  assert.equal(h.sent[1].ThreadName, "新名称");
  assert.equal(h.sent[0].Id, h.sent[1].Id);
  h.switchSession("session-2");
  await h.test();
  await other.test();
  assert.notEqual(h.sent[0].Id, h.sent[2].Id);
  assert.notEqual(h.sent[0].Id, other.sent[0].Id);
  assert.ok(!JSON.stringify(h.sent).includes("PRIVATE"));
});

test("non-TUI and unsupported platforms never invoke the helper", async () => {
  for (const mode of ["rpc", "json", "print"]) {
    const h = harness(); h.ctx.mode = mode;
    await h.emit("session_start"); await h.test();
    assert.equal(h.sent.length, 0); assert.equal(h.notices.length, 0);
  }
  for (const options of [{ platform: "linux" }, { env: {} }]) {
    const h = harness(options);
    await h.emit("session_start"); await h.test();
    assert.equal(h.sent.length, 0); assert.equal(h.notices.length, 1);
  }
});

test("helper failure fails open, warns once, and does not poison queue", async () => {
  let attempts = 0;
  const h = harness({ send: async () => { attempts++; throw new Error("PRIVATE error"); } });
  await h.emit("session_start"); await h.test(); await h.test();
  assert.equal(attempts, 3);
  assert.equal(h.notices.length, 1);
  assert.ok(!JSON.stringify(h.notices).includes("PRIVATE"));
});

test("sends are serialized; shutdown aborts active send and skips pending work", async () => {
  let release, signal, calls = 0;
  const h = harness({ send: async (_helper, _event, s) => {
    calls++; signal = s;
    await new Promise(resolve => { release = resolve; });
  } });
  await h.emit("session_start");
  await h.emit("ui_prompt_start");
  assert.equal(calls, 1);
  await h.emit("session_shutdown");
  assert.ok(signal.aborted);
  release(); await tick();
  await h.test();
  assert.equal(calls, 1);
});

test("metadata is bounded and empty names retain directory fallback", async () => {
  const h = harness(); h.rename("名".repeat(10000));
  await h.test();
  assert.equal(h.sent[0].ThreadName.length, 256);
  h.rename(""); await h.test();
  assert.equal(h.sent[1].ThreadName, "");
});
