import { defineConfig, devices } from "@playwright/test";

/**
 * End-to-end tests run a real browser against the real stack:
 * Next.js (this app) → proxy → Django → PostgreSQL, seeded with `seed_demo`.
 * Start the backend first (see README); Playwright starts Next itself.
 */
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false, // tests share one seeded database
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["github"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:3000",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: process.env.E2E_BASE_URL
    ? undefined
    : {
        command: process.env.CI ? "npm run start:standalone" : "npm run dev",
        url: "http://localhost:3000/login",
        reuseExistingServer: !process.env.CI,
        timeout: 120_000,
      },
});
