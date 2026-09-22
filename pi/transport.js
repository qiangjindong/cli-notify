import { spawn } from "node:child_process";

/** Send JSON on stdin, never through shell interpolation or command-line text. */
export function sendEvent(helper, event, signal, { spawnProcess = spawn, timeoutMs = 10000 } = {}) {
  return new Promise((resolve, reject) => {
    const input = JSON.stringify(event);
    if (Buffer.byteLength(input, "utf8") > 16384) {
      reject(new Error("notification payload too large"));
      return;
    }
    const child = spawnProcess(helper, ["--pi-send"], {
      stdio: ["pipe", "ignore", "ignore"],
      windowsHide: true,
      shell: false,
      signal,
    });
    const timer = setTimeout(() => {
      child.kill();
      finish(new Error("notification helper timed out"));
    }, timeoutMs);
    let done = false;
    function finish(error) {
      if (done) return;
      done = true;
      clearTimeout(timer);
      if (error) reject(error);
      else resolve();
    }
    child.once("error", finish);
    child.once("close", (code) => finish(code === 0 ? undefined : new Error("notification helper failed")));
    child.stdin.on("error", (error) => { child.kill(); finish(error); });
    child.stdin.end(input, "utf8");
  });
}
