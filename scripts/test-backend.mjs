import { execFileSync, spawn } from "node:child_process";
import { mkdirSync } from "node:fs";
import path from "node:path";

const root = process.cwd();
mkdirSync(path.join(root, ".local"), { recursive: true });
const databaseEnv = JSON.parse(
  execFileSync("uv", ["run", "--no-sync", "python", "-m", "app.cli.database", "browser-env"], {
    encoding: "utf8",
    windowsHide: true,
  }),
);
const env = {
  ...process.env,
  ...databaseEnv,
  APP_MODE: process.env.LEARNFLOW_TEST_MODE || "multiuser",
  STORAGE_PATH: path.join(root, ".local", "browser-storage"),
  ALLOWED_ORIGINS: '["http://127.0.0.1:3100"]',
  COOKIE_SECURE: "false",
  EXTRACTION_AUTO_START: "false",
  DOCUMENT_AUTO_ORGANIZE: "false",
  EMBEDDING_AUTO_INDEX: "false",
};
execFileSync(
  "uv",
  ["run", "--no-sync", "alembic", "-c", "backend/alembic.ini", "upgrade", "head"],
  { env, stdio: "inherit", windowsHide: true },
);
const server = spawn(
  "uv",
  [
    "run",
    "--no-sync",
    "uvicorn",
    "browser_server:app",
    "--app-dir",
    "backend/tests",
    "--host",
    "127.0.0.1",
    "--port",
    "8001",
  ],
  { env, stdio: "inherit", windowsHide: true },
);
server.on("exit", (code) => process.exit(code ?? 1));
for (const signal of ["SIGINT", "SIGTERM"]) process.on(signal, () => server.kill());
