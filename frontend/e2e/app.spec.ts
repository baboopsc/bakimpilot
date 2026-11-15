import { expect, test } from "@playwright/test";

import { PASSWORD, login, logout } from "./helpers";

test("unauthenticated users are sent to login", async ({ page }) => {
  await page.goto("/due");
  await expect(page).toHaveURL(/\/login\?next=%2Fdue/);
});

test("wrong password shows an error", async ({ page }) => {
  await page.goto("/login");
  await page.getByLabel("Username").fill("planner");
  await page.getByLabel("Password").fill("wrong");
  await page.getByRole("button", { name: "Log in" }).click();
  await expect(page.getByText("Wrong username or password.")).toBeVisible();
});

test("dashboard shows fleet readiness and grounded aircraft", async ({ page }) => {
  await login(page, "viewer");
  await expect(page.getByRole("heading", { name: "Fleet overview" })).toBeVisible();
  await expect(page.getByText("Fleet readiness")).toBeVisible();
  await expect(page.getByText("Grounded").first()).toBeVisible();
});

test("session survives a page reload (refresh cookie)", async ({ page }) => {
  await login(page, "viewer");
  await page.reload();
  await expect(page.getByRole("heading", { name: "Fleet overview" })).toBeVisible();
});

test("viewer sees no write actions", async ({ page }) => {
  await login(page, "viewer");
  await page.goto("/work-orders");
  await expect(page.getByRole("heading", { name: "Work orders" })).toBeVisible();
  await expect(page.getByRole("button", { name: "New work order" })).toHaveCount(0);
});

test("full work order lifecycle: create → technician signs → planner certifies", async ({ page }) => {
  const title = `E2E inspection ${Date.now()}`;

  // Planner creates an ad-hoc work order with a checklist, assigned to "tech".
  await login(page, "planner");
  await page.goto("/work-orders");
  await page.getByRole("button", { name: "New work order" }).click();
  await page.getByRole("combobox", { name: "Aircraft" }).selectOption({ label: "TB2-T004" });
  await page.getByLabel("Title").fill(title);
  await page.getByRole("combobox", { name: "Technician" }).selectOption({ label: "Elif Demir" });
  await page.getByLabel("Checklist (one item per line)").fill("Inspect wing\nCheck tyres");
  await page.getByRole("button", { name: "Create" }).click();
  await expect(page.getByRole("heading", { name: new RegExp(title) })).toBeVisible();
  const url = page.url();
  await logout(page);

  // Technician starts, ticks both items, signs with password.
  await login(page, "tech");
  await page.goto(url);
  await page.getByRole("button", { name: "Start work" }).click();
  await page.getByRole("button", { name: "Mark done: Inspect wing" }).click();
  await expect(page.getByText("Checklist (1/2)")).toBeVisible();
  await page.getByRole("button", { name: "Mark done: Check tyres" }).click();
  await expect(page.getByText("Checklist (2/2)")).toBeVisible();
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign off as technician" }).click();
  await expect(page.getByText("Awaiting inspection")).toBeVisible();
  await logout(page);

  // Planner (a different person) certifies.
  await login(page, "planner");
  await page.goto(url);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Certify & close" }).click();
  await expect(page.getByText("Closed", { exact: true })).toBeVisible();
  await expect(page.getByText("Signed content unchanged")).toBeVisible();
  await expect(page.getByText("Inspector certified and closed")).toBeVisible();
});

test("AI assistant answers from the manual with a page citation", async ({ page }) => {
  await login(page, "tech");
  await page.goto("/assistant?tab=manuals");
  await page.getByRole("button", { name: "What torque for the oil drain plug?" }).click();
  await expect(page.getByText(/25 Nm/).first()).toBeVisible();
  await expect(page.getByRole("button", { name: /page 2/ })).toBeVisible();
});

test("natural-language data question in Turkish", async ({ page }) => {
  await login(page, "viewer");
  await page.goto("/assistant?tab=data");
  await page.getByRole("button", { name: "Hangi uçaklar yerde?" }).click();
  await expect(page.getByText("airworthiness=GROUNDED", { exact: true })).toBeVisible();
  await expect(page.getByRole("cell", { name: "TB2-T003" })).toBeVisible();
});
