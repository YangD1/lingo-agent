import { defineConfig, devices } from "@playwright/test";

const port = Number(process.env.E2E_PORT ?? 3100);
const backendPort = Number(process.env.E2E_BACKEND_PORT ?? 8100);
const llmPort = Number(process.env.E2E_LLM_PORT ?? 8101);

// Real backend on a throwaway database + a fake OpenAI-compatible model + a production
// build of the frontend.
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
      command: "uv run --project ../backend python e2e/fake_llm.py",
      url: `http://127.0.0.1:${llmPort}/healthz`,
      env: { E2E_LLM_PORT: String(llmPort) },
      reuseExistingServer: !process.env.CI,
    },
    {
      command: "uv run --project ../backend python e2e/run_backend.py",
      url: `http://127.0.0.1:${backendPort}/healthz`,
      env: { E2E_BACKEND_PORT: String(backendPort) },
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
    },
    {
      // Rewrites are baked in at build time, so build against the e2e backend.
      // `pnpm start` runs the standalone server, the same artifact as the Docker image.
      command: "pnpm build && pnpm start",
      url: `http://localhost:${port}`,
      env: { BACKEND_URL: `http://127.0.0.1:${backendPort}`, PORT: String(port), HOSTNAME: "127.0.0.1" },
      reuseExistingServer: !process.env.CI,
      timeout: 180_000,
    },
  ],
});
