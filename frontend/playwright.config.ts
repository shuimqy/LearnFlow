import path from "node:path";
import { defineConfig } from "@playwright/test";

const root = path.resolve(__dirname, "..");

export default defineConfig({
  testDir: "./tests",
  fullyParallel: false,
  workers: 1,
  timeout: 45_000,
  reporter: "list",
  use: {
    baseURL: "http://127.0.0.1:3100",
    channel: "msedge",
    headless: true,
    viewport: { width: 1440, height: 1000 },
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
  },
  webServer: [
    {
      command: "node scripts/test-backend.mjs",
      cwd: root,
      url: "http://127.0.0.1:8001/api/health",
      timeout: 60_000,
      reuseExistingServer: false,
    },
    {
      command: "npm run dev -- --port 3100",
      url: "http://127.0.0.1:3100/login",
      env: {
        API_ORIGIN: "http://127.0.0.1:8001",
        NEXT_TELEMETRY_DISABLED: "1",
        NEXT_DIST_DIR: ".next-e2e",
      },
      timeout: 60_000,
      reuseExistingServer: false,
    },
  ],
});
