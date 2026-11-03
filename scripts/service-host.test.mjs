import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { once } from "node:events";
import { mkdtemp, rmdir, unlink, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const hostPath = fileURLToPath(new URL("./service-host.mjs", import.meta.url));
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const alive = (pid) => {
  try {
    process.kill(pid, 0);
    return true;
  } catch (error) {
    if (error.code === "ESRCH") return false;
    throw error;
  }
};

function startHost(command, args, env = {}) {
  return spawn(process.execPath, [hostPath, command, ...args], {
    stdio: ["ignore", "pipe", "pipe", "ipc"],
    windowsHide: true,
    detached: true,
    env: { ...process.env, ...env },
  });
}

async function childInfo(process) {
  let output = "";
  for await (const chunk of process.stdout) {
    output += chunk;
    if (output.includes("\n")) return JSON.parse(output.split("\n")[0]);
  }
  throw new Error("The test service did not start.");
}

async function eventuallyStopped(pid) {
  for (let attempt = 0; attempt < 100 && alive(pid); attempt++) await sleep(50);
  assert.equal(alive(pid), false, `Test process ${pid} was not stopped`);
}

const serviceCode = `
  const {spawn}=require('node:child_process');
  const descendant=spawn(process.execPath,['-e','setInterval(()=>{},1000)'],{windowsHide:true,stdio:'ignore'});
  console.log(JSON.stringify({pid:process.pid,descendant:descendant.pid}));
  setInterval(()=>{},1000);
`;

test("stopping a host only stops its own service", { timeout: 15_000 }, async (t) => {
  const unrelated = spawn(process.execPath, ["-e", "setInterval(()=>{},1000)"], {
    windowsHide: true,
  });
  t.after(() => unrelated.kill());
  const host = startHost(process.execPath, ["-e", serviceCode]);
  t.after(() => {
    if (host.connected) host.send({ command: "stop" });
  });
  const { pid, descendant } = await childInfo(host);
  assert.equal(alive(pid), true);
  const exited = once(host, "close");
  host.send({ command: "stop" });
  assert.equal((await exited)[0], 0);
  await eventuallyStopped(pid);
  await eventuallyStopped(descendant);
  assert.equal(alive(unrelated.pid), true);
});

test("a killed launcher leaves no running service", { timeout: 15_000 }, async (t) => {
  const parentCode = `
    const {spawn}=require('node:child_process');
    const host=spawn(process.execPath,[process.argv[1],process.execPath,'-e',process.argv[2]],{
      windowsHide:true,detached:true,stdio:['ignore','inherit','inherit','ipc']
    });
    process.on('message',()=>{});
  `;
  const parent = spawn(process.execPath, ["-e", parentCode, hostPath, serviceCode], {
    windowsHide: true,
    stdio: ["ignore", "pipe", "pipe", "ipc"],
  });
  t.after(() => parent.kill());
  const { pid, descendant } = await childInfo(parent);
  assert.equal(alive(pid), true);
  parent.kill();
  await eventuallyStopped(pid);
  await eventuallyStopped(descendant);
});

test("service startup errors propagate as failures", { timeout: 15_000 }, async () => {
  const host = startHost(path.join(path.dirname(hostPath), "missing-service.exe"), []);
  assert.equal((await once(host, "close"))[0], 1);
});

test("a service exit code is preserved", { timeout: 15_000 }, async () => {
  const host = startHost(process.execPath, ["-e", "process.exit(7)"]);
  assert.equal((await once(host, "close"))[0], 7);
});

test(
  "Python edits replace the service while the host remains available",
  { timeout: 15_000 },
  async (t) => {
    const folder = await mkdtemp(path.join(os.tmpdir(), "learnflow-host-"));
    const source = path.join(folder, "sample.py");
    await writeFile(source, "first");
    const code = `console.log(JSON.stringify({pid:process.pid,value:require('node:fs').readFileSync(process.argv[1],'utf8')}));setInterval(()=>{},1000)`;
    const host = startHost(process.execPath, ["-e", code, source], {
      LEARNFLOW_RELOAD_DIR: folder,
    });
    t.after(async () => {
      if (host.connected) {
        const exited = once(host, "close");
        host.send({ command: "stop" });
        await exited;
      }
      await unlink(source);
      await rmdir(folder);
    });
    const seen = [];
    let buffer = "";
    host.stdout.on("data", (chunk) => {
      buffer += chunk;
      const lines = buffer.split("\n");
      buffer = lines.pop();
      for (const line of lines) {
        if (line.startsWith("{")) seen.push(JSON.parse(line));
      }
    });
    for (let i = 0; i < 100 && !seen.length; i++) await sleep(50);
    assert.equal(seen[0]?.value, "first");
    await writeFile(source, "second");
    for (let i = 0; i < 100 && !seen.some((entry) => entry.value === "second"); i++)
      await sleep(50);
    const latest = seen.find((entry) => entry.value === "second");
    assert.ok(latest);
    assert.notEqual(latest.pid, seen[0].pid);
    await eventuallyStopped(seen[0].pid);
    assert.equal(alive(host.pid), true);
    const exited = once(host, "close");
    host.send({ command: "stop" });
    assert.equal((await exited)[0], 0);
    await eventuallyStopped(latest.pid);
  },
);
