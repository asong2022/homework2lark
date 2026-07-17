import { defineConfig, devices } from "@playwright/test";
import path from "node:path";

const webRoot = process.cwd();
const apiRoot = path.resolve(webRoot, "../api");

export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 2 : 0,
  reporter: [["list"], ["html", { open: "never" }]],
  use: {
    baseURL: "http://127.0.0.1:3001",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
  webServer: [
    {
      command: "uv run python scripts/start_e2e.py",
      cwd: apiRoot,
      url: "http://127.0.0.1:8001/api/v1/health",
      timeout: 120_000,
      reuseExistingServer: !process.env.CI,
      env: {
        ...process.env,
        APP_ENV: "test",
        DATABASE_URL: "sqlite:///./data/e2e.db",
        STORAGE_ROOT: "./data/e2e-storage",
        CORS_ORIGINS: "http://127.0.0.1:3001",
        OCR_PROVIDER: "paddleocr_vl_api",
        PADDLEOCR_ACCESS_TOKEN: "e2e-not-used",
        REGION_DETECTION_PROVIDER: "manual",
        PROBLEM_PUBLISHER: "lark_cli",
      },
    },
    {
      command: "npm run dev -- --hostname 127.0.0.1 --port 3001",
      cwd: webRoot,
      url: "http://127.0.0.1:3001",
      timeout: 120_000,
      reuseExistingServer: !process.env.CI,
      env: {
        ...process.env,
        NEXT_PUBLIC_API_BASE_URL: "http://127.0.0.1:8001/api/v1",
      },
    },
  ],
});
