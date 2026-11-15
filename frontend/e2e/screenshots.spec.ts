import { test } from "@playwright/test";

import { login } from "./helpers";

// Not a test of behaviour: captures every page for a visual review.
// Run with: npx playwright test screenshots --grep @screens
const DIR = process.env.SCREENSHOTS_DIR ?? "screenshots";
const PAGES = ["/", "/aircraft", "/aircraft/3", "/due", "/work-orders", "/inventory", "/alerts", "/assistant?tab=anomalies", "/manuals"];

test("@screens capture pages", async ({ page }) => {
  test.skip(!process.env.SCREENSHOTS, "set SCREENSHOTS=1 to capture");
  await page.setViewportSize({ width: 1440, height: 900 });
  await login(page, "planner");
  for (const path of PAGES) {
    await page.goto(path);
    await page.waitForLoadState("networkidle");
    const name = path === "/" ? "dashboard" : path.replace(/[/?=]/g, "_").replace(/^_/, "");
    await page.screenshot({ path: `${DIR}/${name}.png`, fullPage: true });
  }
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await page.waitForLoadState("networkidle");
  await page.screenshot({ path: `${DIR}/dashboard-mobile.png`, fullPage: true });
});
