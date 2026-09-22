import test from "node:test";
import assert from "node:assert/strict";
import { EventEmitter } from "node:events";
import { PassThrough } from "node:stream";
import { sendEvent } from "../../pi/transport.js";

function fakeSpawn(onStart) {
  const child = new EventEmitter();
  child.stdin = new PassThrough();
  child.killed = false;
  child.kill = () => { child.killed = true; };
  let input = "";
  child.stdin.on("data", chunk => { input += chunk.toString("utf8"); });
  return {
    child, input: () => input,
    spawnProcess: (helper, args, options) => { onStart?.(helper, args, options, child); return child; },
  };
}

test("transport uses a hidden direct process and UTF-8 stdin, not shell/argv text", async () => {
  const controller = new AbortController();
  const event = { ThreadName: "中文 & ' $()", Kind: "test" };
  const fake = fakeSpawn((helper, args, options, child) => {
    assert.equal(helper, "C:\\中文 空格\\helper.exe");
    assert.deepEqual(args, ["--pi-send"]);
    assert.equal(options.shell, false);
    assert.equal(options.windowsHide, true);
    assert.equal(options.signal, controller.signal);
    setImmediate(() => child.emit("close", 0));
  });
  await sendEvent("C:\\中文 空格\\helper.exe", event, controller.signal, fake);
  assert.deepEqual(JSON.parse(fake.input()), event);
});

test("nonzero exit, spawn failure, broken stdin and timeout reject without hanging", async () => {
  for (const mode of ["exit", "spawn", "stdin", "timeout"]) {
    const fake = fakeSpawn((_helper, _args, _options, child) => {
      setImmediate(() => {
        if (mode === "exit") child.emit("close", 1);
        if (mode === "spawn") child.emit("error", new Error("ENOENT"));
        if (mode === "stdin") child.stdin.emit("error", new Error("EPIPE"));
      });
    });
    await assert.rejects(sendEvent("helper.exe", {}, undefined, { ...fake, timeoutMs: 20 }));
    if (mode === "stdin" || mode === "timeout") assert.ok(fake.child.killed);
  }
});

test("oversized payload rejected before spawn", async () => {
  await assert.rejects(sendEvent("helper.exe", { text: "名".repeat(6000) }, undefined, {
    spawnProcess: () => { assert.fail("must not spawn"); },
  }), /too large/);
});
