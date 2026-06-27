import { defineConfig, devices } from "@playwright/test";

// Run the stack first (`make dev` + `cd web && npm run dev`), then `npm run e2e`.
// Browsers must be installed once: `npx playwright install chromium`.
export default defineConfig({
  testDir: "./e2e",
  timeout: 30_000,
  use: {
    baseURL: process.env.PLAYWRIGHT_BASE_URL || "http://localhost:5173/admin/",
    trace: "on-first-retry",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
