import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  resolve: { tsconfigPaths: true },
  test: {
    environment: "jsdom",
    include: ["src/**/*.test.{ts,tsx}"],
    setupFiles: ["./vitest.setup.ts"],
    // The full parallel run is much slower per test than one file alone (see vitest.setup.ts).
    testTimeout: 15_000,
    // One jsdom worker per core (31 on a 32-core machine) peaked at 7.4 GB of an 8 GB WSL
    // and starved tests into timeouts; 8 workers peak near 4 GB and take about as long.
    maxWorkers: 8,
  },
});
