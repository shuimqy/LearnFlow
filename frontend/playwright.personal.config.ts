import { defineConfig } from "@playwright/test";
import config from "./playwright.config";

export default defineConfig({
  ...config,
  testMatch: "personal.spec.ts",
  webServer:
    config.webServer && Array.isArray(config.webServer)
      ? config.webServer.map((server, index) =>
          index === 0
            ? { ...server, env: { ...server.env, LEARNFLOW_TEST_MODE: "personal" } }
            : server,
        )
      : config.webServer,
});
