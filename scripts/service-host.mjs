import { spawn } from "node:child_process";
import { watch } from "node:fs";

const [command, ...args] = process.argv.slice(2);
if (!command || !process.connected) {
  console.error("This process must be started by the LearnFlow launcher.");
  process.exit(1);
}

let current;
let watcher;
let debounce;
let closing = false;
let cleanup;
let restarting = false;
let changed = false;

function closeWatcher() {
  clearTimeout(debounce);
  watcher?.close();
  watcher = undefined;
}

function start() {
  const env = { ...process.env };
  delete env.LEARNFLOW_RELOAD_DIR;
  const child = spawn(command, args, {
    env,
    windowsHide: true,
    detached: process.platform !== "win32",
    stdio: ["ignore", "inherit", "inherit"],
  });
  const entry = { child, finished: false, intentional: false, failed: false };
  entry.closed = new Promise((resolve) => {
    child.once("error", () => {
      entry.failed = true;
      console.error(`Could not start ${command}. Check the executable and project dependencies.`);
    });
    child.once("close", (code) => {
      entry.finished = true;
      resolve();
      if (!entry.intentional && !closing) {
        process.exitCode = entry.failed ? 1 : (code ?? 1);
        closeWatcher();
        if (process.connected) process.disconnect();
      }
    });
  });
  current = entry;
}

async function terminate(entry) {
  entry.intentional = true;
  if (!entry.finished && entry.child.pid) {
    if (process.platform === "win32") {
      await new Promise((resolve) => {
        const killer = spawn("taskkill.exe", ["/PID", String(entry.child.pid), "/T", "/F"], {
          windowsHide: true,
          stdio: "ignore",
        });
        killer.once("error", resolve);
        killer.once("close", resolve);
      });
    } else {
      try {
        process.kill(-entry.child.pid, "SIGTERM");
      } catch (error) {
        if (error.code !== "ESRCH") throw error;
      }
    }
  }
  await entry.closed;
}

function stop() {
  if (cleanup) return cleanup;
  closing = true;
  closeWatcher();
  // 控制通道断开时只清理自己持有的进程树，包括正在重载的服务。
  cleanup = terminate(current).finally(() => {
    if (process.connected) process.disconnect();
  });
  cleanup.catch(() => {
    process.exitCode = 1;
  });
  return cleanup;
}

async function reload() {
  changed = true;
  if (restarting || closing) return;
  restarting = true;
  try {
    while (changed && !closing) {
      changed = false;
      // Windows 隐藏窗口无法可靠投递 Uvicorn 的 CTRL_C_EVENT，直接替换所持有的进程树。
      await terminate(current);
      if (!closing) {
        console.log("Python source changed. Restarting backend...");
        start();
      }
    }
  } finally {
    restarting = false;
  }
}

process.on("message", (message) => {
  if (message?.command === "stop") void stop();
});
process.on("disconnect", () => void stop());
for (const signal of ["SIGINT", "SIGTERM", "SIGHUP"]) {
  process.on(signal, () => void stop());
}

start();
if (process.env.LEARNFLOW_RELOAD_DIR) {
  try {
    watcher = watch(process.env.LEARNFLOW_RELOAD_DIR, { recursive: true }, (_event, filename) => {
      if (filename && !String(filename).endsWith(".py")) return;
      clearTimeout(debounce);
      debounce = setTimeout(
        () =>
          void reload().catch(() => {
            process.exitCode = 1;
            void stop();
          }),
        350,
      );
    });
    watcher.on("error", () => {
      process.exitCode = 1;
      void stop();
    });
  } catch {
    console.error("Could not watch Python source files.");
    process.exitCode = 1;
    void stop();
  }
}
