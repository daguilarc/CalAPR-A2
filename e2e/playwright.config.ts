import { defineConfig } from "@playwright/test";
import path from "node:path";

const repoRoot = path.resolve(__dirname, "..");
const docsPath = path.join(repoRoot, "docs");

export default defineConfig({
  testDir: __dirname,
  testMatch: "explorer.spec.ts",
  timeout: 60_000,
  globalSetup: path.join(__dirname, "global-setup.ts"),
  use: {
    baseURL: "http://127.0.0.1:8765",
    headless: true,
  },
  webServer: {
    command: `python3 -m http.server 8765 --directory "${docsPath}"`,
    url: "http://127.0.0.1:8765",
    reuseExistingServer: true,
    timeout: 60_000,
  },
});
