import { defineConfig, devices } from "@playwright/test";

const backendPort = 8010;
const frontendPort = 3010;

export default defineConfig({
  testDir: "./e2e",
  timeout: 120_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  retries: process.env.CI ? 1 : 0,
  reporter: [["list"], ["html", { open: "never" }]],
  use: {
    baseURL: `http://localhost:${frontendPort}`,
    trace: "retain-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: [
    {
      command: `cd ../backend && LLM_MODE=${process.env.LLM_MODE ?? "mock"} APP_ENV=test PORT=${backendPort} FRONTEND_ORIGIN=http://localhost:${frontendPort} BACKGROUND_MAX_NODES=${process.env.BACKGROUND_MAX_NODES ?? 200} DATABASE_URL=sqlite+aiosqlite:///./.e2e/e2e.db WORKSPACE_DIR=./.e2e/workspace uv run uvicorn app.main:app --port ${backendPort}`,
      url: `http://localhost:${backendPort}/api/health`,
      reuseExistingServer: false,
      timeout: 120_000,
    },
    {
      command: `NEXT_PUBLIC_API_URL=http://localhost:${backendPort} PORT=${frontendPort} pnpm dev`,
      url: `http://localhost:${frontendPort}`,
      reuseExistingServer: false,
      timeout: 180_000,
    },
  ],
});
