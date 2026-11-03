import { spawn } from "node:child_process";
import { createHash } from "node:crypto";
import { createWriteStream, existsSync, realpathSync } from "node:fs";
import { mkdir, readFile, unlink, writeFile } from "node:fs/promises";
import net from "node:net";
import path from "node:path";
import { createInterface } from "node:readline";
import { fileURLToPath } from "node:url";

const root = realpathSync(path.resolve(path.dirname(fileURLToPath(import.meta.url)), ".."));
const frontend = path.join(root, "frontend");
const runtime = path.join(root, ".local", "dev");
const logs = path.join(root, ".local", "logs");
const project = process.platform === "win32" ? root.toLowerCase() : root;
const identifier = createHash("sha256").update(project).digest("hex").slice(0, 20);
const controlPath =
  process.platform === "win32"
    ? `\\\\.\\pipe\\learnflow-${identifier}`
    : path.join(runtime, "control.sock");
const frontendUrl = "http://127.0.0.1:3000";
const backendUrl = "http://127.0.0.1:8000";
const children = new Set();
const supervised = new Set();
let server;
let state = "starting";
let stopping = false;
let cleanup;

const sleep = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds));

function control(command) {
  return new Promise((resolve, reject) => {
    const socket = net.createConnection(controlPath);
    let buffer = "";
    socket.setTimeout(3000, () => socket.destroy(new Error("The launcher did not respond.")));
    socket.once("connect", () => socket.write(JSON.stringify({ command, project }) + "\n"));
    socket.on("data", (chunk) => {
      buffer += chunk;
      if (!buffer.includes("\n")) return;
      socket.end();
      try {
        const result = JSON.parse(buffer.split("\n")[0]);
        if (result.project !== project) throw new Error("The launcher belongs to another project.");
        resolve(result);
      } catch (error) {
        reject(error);
      }
    });
    socket.once("error", (error) => {
      if (["ENOENT", "ECONNREFUSED"].includes(error.code)) resolve(null);
      else reject(error);
    });
    socket.once("end", () => {
      if (!buffer.includes("\n")) reject(new Error("The launcher closed the connection."));
    });
  });
}

async function createControlServer() {
  await mkdir(runtime, { recursive: true });
  if (process.platform !== "win32")
    await unlink(controlPath).catch((error) => {
      if (error.code !== "ENOENT") throw error;
    });
  server = net.createServer((socket) => {
    let buffer = "";
    socket.setTimeout(3000, () => socket.destroy());
    socket.on("error", () => {});
    socket.on("data", (chunk) => {
      buffer += chunk;
      if (buffer.length > 4096) {
        socket.destroy();
        return;
      }
      if (!buffer.includes("\n")) return;
      try {
        const request = JSON.parse(buffer.split("\n")[0]);
        if (request.project !== project || !["status", "stop"].includes(request.command)) {
          socket.destroy();
          return;
        }
        socket.end(JSON.stringify({ project, state, frontendUrl, backendUrl, logs }) + "\n");
        if (request.command === "stop") setTimeout(() => void shutdown(), 50);
      } catch {
        socket.destroy();
      }
    });
  });
  await new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(controlPath, resolve);
  });
}

async function assertPortAvailable(port) {
  const probe = net.createServer();
  await new Promise((resolve, reject) => {
    probe.once("error", () =>
      reject(
        new Error(
          `Port ${port} is already in use. Close the existing service, then run start.bat again.`,
        ),
      ),
    );
    probe.listen(port, "127.0.0.1", () => probe.close(resolve));
  });
}

function launch(label, command, args, options = {}) {
  if (stopping) throw new Error("Startup cancelled.");
  const env = { ...process.env, NO_COLOR: "1", ...options.env };
  delete env.FORCE_COLOR;
  const log = createWriteStream(path.join(logs, `${label}.log`), {
    flags: "a",
  });
  log.write(`\n--- ${new Date().toISOString()} ---\n`);
  const useHost = Boolean(options.service);
  const child = spawn(
    useHost ? process.execPath : command,
    useHost ? [path.join(root, "scripts", "service-host.mjs"), command, ...args] : args,
    {
      cwd: options.cwd || root,
      env,
      windowsHide: true,
      detached: useHost || process.platform !== "win32",
      stdio: useHost ? ["ignore", "pipe", "pipe", "ipc"] : ["ignore", "pipe", "pipe"],
    },
  );
  children.add(child);
  if (useHost) supervised.add(child);
  for (const input of [child.stdout, child.stderr]) {
    createInterface({ input }).on("line", (line) => {
      console.log(`[${label}] ${line}`);
      log.write(`${new Date().toISOString()} ${line}\n`);
    });
  }
  const done = new Promise((resolve, reject) => {
    child.once("error", (error) => {
      children.delete(child);
      supervised.delete(child);
      log.end();
      reject(new Error(`Could not start ${command}: ${error.message}`));
    });
    child.once("close", (code) => {
      children.delete(child);
      supervised.delete(child);
      log.end();
      if (!code || stopping) resolve();
      else
        reject(
          new Error(`${label} exited with code ${code}. See ${path.join(logs, `${label}.log`)}`),
        );
      if (options.service && !stopping) {
        console.error(`${label} stopped unexpectedly. Stopping the other service.`);
        void shutdown(1);
      }
    });
  });
  done.catch(() => {});
  return done;
}

async function terminate(child) {
  if (!children.has(child) || !child.pid || child.exitCode !== null) return;
  if (supervised.has(child) && child.connected) {
    await new Promise((resolve) => {
      const timer = setTimeout(resolve, 10_000);
      child.once("close", () => {
        clearTimeout(timer);
        resolve();
      });
      child.send({ command: "stop" }, () => {});
    });
    if (child.exitCode !== null) return;
  }
  if (process.platform === "win32") {
    // 只结束本次启动持有的进程树，避免按端口误杀其他服务。
    await new Promise((resolve) => {
      const killer = spawn("taskkill.exe", ["/PID", String(child.pid), "/T", "/F"], {
        windowsHide: true,
        stdio: "ignore",
      });
      killer.once("error", resolve);
      killer.once("close", resolve);
    });
  } else {
    try {
      process.kill(-child.pid, "SIGTERM");
    } catch (error) {
      if (error.code !== "ESRCH") throw error;
    }
  }
}

function shutdown(code = 0) {
  if (cleanup) return cleanup;
  stopping = true;
  state = "stopping";
  cleanup = (async () => {
    console.log("Stopping LearnFlow...");
    await Promise.all([...children].map(terminate));
    if (server?.listening) await new Promise((resolve) => server.close(resolve));
    console.log("LearnFlow stopped.");
    process.exitCode = code;
  })();
  return cleanup;
}

async function waitForHttp(url, timeout = 90_000) {
  const deadline = Date.now() + timeout;
  while (!stopping && Date.now() < deadline) {
    try {
      const response = await fetch(url, { signal: AbortSignal.timeout(2000) });
      await response.body?.cancel();
      if (response.ok) return;
    } catch {}
    await sleep(400);
  }
  throw new Error(stopping ? "Startup cancelled." : `Timed out waiting for ${url}. See ${logs}`);
}

function openBrowser() {
  const command =
    process.platform === "win32"
      ? "rundll32.exe"
      : process.platform === "darwin"
        ? "open"
        : "xdg-open";
  const args =
    process.platform === "win32" ? ["url.dll,FileProtocolHandler", frontendUrl] : [frontendUrl];
  const browser = spawn(command, args, {
    detached: true,
    stdio: "ignore",
    windowsHide: true,
  });
  browser.once("error", () => console.log(`Open ${frontendUrl} in your browser.`));
  browser.unref();
}

async function setup() {
  console.log("Checking Python dependencies with uv...");
  await launch("setup", "uv", ["sync", "--locked", "--all-packages"]);
  if (!existsSync(path.join(root, ".env"))) {
    await launch("setup", "uv", [
      "run",
      "--locked",
      "--all-packages",
      "python",
      "-m",
      "app.cli.database",
      "setup",
    ]);
  } else {
    await launch("setup", "uv", [
      "run",
      "--locked",
      "--all-packages",
      "python",
      "-m",
      "app.cli.database",
      "ensure",
    ]);
  }
  const lock = await readFile(path.join(frontend, "package-lock.json"));
  const hash = createHash("sha256").update(lock).digest("hex");
  const marker = path.join(runtime, "frontend-lock.sha256");
  const installedHash = await readFile(marker, "utf8").catch(() => "");
  if (
    !existsSync(path.join(frontend, "node_modules", "next", "package.json")) ||
    installedHash !== hash
  ) {
    console.log("Installing frontend dependencies...");
    if (process.platform === "win32") {
      await launch("setup", "cmd.exe", ["/d", "/s", "/c", "npm.cmd ci --no-audit --no-fund"], {
        cwd: frontend,
      });
    } else {
      await launch("setup", "npm", ["ci", "--no-audit", "--no-fund"], {
        cwd: frontend,
      });
    }
    await writeFile(marker, hash);
  }
  console.log("Applying database migrations...");
  await launch("setup", "uv", [
    "run",
    "--locked",
    "--all-packages",
    "alembic",
    "-c",
    "backend/alembic.ini",
    "upgrade",
    "head",
  ]);
  await launch("setup", "uv", [
    "run",
    "--locked",
    "--all-packages",
    "python",
    "-m",
    "app.cli.queue",
    "setup",
  ]);
}

async function startQueue() {
  const { execFile } = await import("node:child_process");
  const check = () =>
    new Promise((resolve) => {
      execFile(
        "uv",
        ["run", "--locked", "--all-packages", "python", "-m", "app.cli.queue", "check"],
        { cwd: root, windowsHide: true },
        (error) => resolve(!error),
      );
    });
  if (!(await check())) {
    void launch(
      "redis",
      "uv",
      ["run", "--locked", "--all-packages", "python", "-m", "app.cli.queue", "serve"],
      { service: true },
    );
    let ready = false;
    for (let attempt = 0; attempt < 20 && !stopping; attempt++) {
      if (await check()) {
        ready = true;
        break;
      }
      await sleep(300);
    }
    if (!ready) throw new Error("Redis did not start. See .local/logs/redis.log.");
  }
  void launch(
    "worker",
    "uv",
    ["run", "--locked", "--all-packages", "python", "-m", "app.workers.main"],
    { service: true },
  );
}

async function main() {
  const [major, minor] = process.versions.node.split(".").map(Number);
  if (major < 20 || (major === 20 && minor < 9))
    throw new Error("Node.js 20.9 or later is required.");
  const command = process.argv[2] || "start";
  if (!["start", "stop", "status"].includes(command))
    throw new Error("Usage: node scripts/dev.mjs [start|stop|status] [--no-open]");
  const existing = await control(command === "stop" ? "stop" : "status");
  if (command === "status") {
    console.log(
      existing ? JSON.stringify(existing, null, 2) : "LearnFlow is not running through start.bat.",
    );
    return;
  }
  if (command === "stop") {
    if (!existing) {
      console.log("No managed LearnFlow service is running.");
      return;
    }
    for (let attempt = 0; attempt < 50; attempt++) {
      await sleep(200);
      if (!(await control("status"))) {
        console.log("LearnFlow stopped.");
        return;
      }
    }
    throw new Error("Stopping took longer than expected. Check the startup window.");
  }
  if (existing) {
    console.log(`LearnFlow is already ${existing.state}. ${frontendUrl}`);
    if (existing.state === "ready" && !process.argv.includes("--no-open")) openBrowser();
    return;
  }
  await mkdir(logs, { recursive: true });
  try {
    await createControlServer();
  } catch (error) {
    if (error.code === "EADDRINUSE" && (await control("status"))) {
      server = undefined;
      console.log("Another LearnFlow launcher is already starting.");
      return;
    }
    throw error;
  }
  for (const signal of ["SIGINT", "SIGTERM", "SIGHUP"]) process.on(signal, () => void shutdown());
  await Promise.all([assertPortAvailable(3000), assertPortAvailable(8000)]);
  console.log(`LearnFlow: ${root}`);
  console.log(`Logs: ${logs}`);
  await setup();
  await startQueue();
  void launch(
    "backend",
    "uv",
    [
      "run",
      "--locked",
      "--all-packages",
      "uvicorn",
      "app.main:app",
      "--host",
      "127.0.0.1",
      "--port",
      "8000",
    ],
    {
      service: true,
      env: { LEARNFLOW_RELOAD_DIR: path.join(root, "backend", "app") },
    },
  );
  await waitForHttp(`${backendUrl}/api/health`);
  void launch(
    "frontend",
    process.execPath,
    [
      path.join(frontend, "node_modules", "next", "dist", "bin", "next"),
      "dev",
      "--hostname",
      "127.0.0.1",
      "--port",
      "3000",
    ],
    { cwd: frontend, service: true, env: { API_ORIGIN: backendUrl } },
  );
  await waitForHttp(`${frontendUrl}/login`);
  await waitForHttp(`${frontendUrl}/api/health`);
  if (stopping) return;
  state = "ready";
  console.log(`\nReady: ${frontendUrl}`);
  console.log(`API docs: ${backendUrl}/docs`);
  console.log("Keep this window open. Use Ctrl+C or stop.bat to stop both services.\n");
  if (!process.argv.includes("--no-open")) openBrowser();
}

main().catch(async (error) => {
  console.error(`\n${error.message}`);
  console.error(`Logs: ${logs}`);
  await shutdown(1);
});
