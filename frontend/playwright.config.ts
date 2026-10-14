import { defineConfig, devices } from "@playwright/test";

const port = Number(process.env.E2E_PORT ?? 3100);
const backendPort = Number(process.env.E2E_BACKEND_PORT ?? 8100);
const llmPort = Number(process.env.E2E_LLM_PORT ?? 8101);
// `make screenshots` (task 72.2) runs only e2e/screenshots.spec.ts, on its own ports and
// database (see the Makefile); `make e2e` never runs it.
const screenshots = !!process.env.SCREENSHOTS;

// The desk pet's reminders (ADR 0039 §4) would pop up a few seconds into any test and could
// cover what it clicks: every test starts with today's reminders used up. `pet.spec.ts`
// clears this to test them.
const pad = (n: number) => String(n).padStart(2, "0");
const now = new Date();
const day = `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
const quietPet = {
  cookies: [],
  origins: [
    {
      origin: `http://localhost:${port}`,
      localStorage: [
        {
          name: "lingo.tutorPet.nudges",
          value: JSON.stringify({ day, said: ["e2e", "e2e", "e2e", "plan_done"], last: now.getTime() }),
        },
      ],
    },
  ],
};

// Real backend on a throwaway database + a fake OpenAI-compatible model + a production
// build of the frontend.
// Needs the compose postgres running (docker compose up -d postgres).
export default defineConfig({
  testDir: "./e2e",
  ...(screenshots ? { testMatch: "screenshots.spec.ts" } : { testIgnore: "screenshots.spec.ts" }),
  fullyParallel: false,
  workers: 1,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? "github" : "list",
  use: {
    baseURL: `http://localhost:${port}`,
    trace: "retain-on-failure",
    storageState: quietPet,
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
      // A full ecdict.csv (screenshots) takes a while to import.
      timeout: screenshots ? 600_000 : 120_000,
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
