import { test, expect } from "@playwright/test";
test("cold-start sign-in failure is recoverable and announced without a false login", async ({
  page,
}) => {
  await page.goto("/login?expired=1");
  await expect(page.getByRole("status")).toContainText("session has expired");
  await page.getByLabel("Username").fill("recovery_user");
  await page
    .getByLabel("Password", { exact: true })
    .fill("test-only-long-password");
  await page.getByRole("button", { name: "Show password" }).click();
  await expect(page.getByLabel("Password", { exact: true })).toHaveAttribute(
    "type",
    "text",
  );
  await page.route("**/api/auth", (route) =>
    route.request().method() === "POST"
      ? route.fulfill({ status: 503, json: { detail: "synthetic cold start" } })
      : route.continue(),
  );
  await page.getByRole("button", { name: "Sign in to workspace" }).click();
  await expect(page.locator("form").getByRole("alert")).toContainText(
    "may be waking up",
  );
  await expect(
    page.locator("form").getByRole("alert").locator(".."),
  ).toBeFocused();
  await expect(
    page.getByRole("button", { name: "Sign in to workspace" }),
  ).toBeEnabled();
  await page.unroute("**/api/auth");
  await page.route("**/api/auth", (route) =>
    route.fulfill({
      status: 429,
      headers: { "Retry-After": "60" },
      json: { detail: "Too many authentication attempts. Try again later." },
    }),
  );
  await page.getByRole("button", { name: "Sign in to workspace" }).click();
  await expect(page.locator("form").getByRole("alert")).toContainText(
    "Try again in 60 seconds",
  );
  await expect(page).toHaveURL(/\/login/);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
});
