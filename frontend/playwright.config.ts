import { defineConfig, devices } from "@playwright/test";

const port = Number(process.env.E2E_PORT ?? 3100);
const backendPort = Number(process.env.E2E_BACKEND_PORT ?? 8100);

// Real backend on a throwaway database + a production build of the frontend.
// Needs the compose postgres running (docker compose up -d postgres).
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? "github" : "list",
  use: {
    baseURL: `http://localhost:${port}`,
    trace: "retain-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: [
    {
      command: "uv run --project ../backend python e2e/run_backend.py",
      url: `http://127.0.0.1:${backendPort}/healthz`,
      env: { E2E_BACKEND_PORT: String(backendPort) },
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
    },
    {
      // Rewrites are baked in at build time, so build against the e2e backend.
      command: `pnpm build && pnpm start -p ${port}`,
      url: `http://localhost:${port}`,
      env: { BACKEND_URL: `http://127.0.0.1:${backendPort}` },
      reuseExistingServer: !process.env.CI,
      timeout: 180_000,
    },
  ],
});
