import { test, expect } from "@playwright/test";
import { readFile } from "node:fs/promises";
test("real backend workflow, honest failure, private session and responsive editor", async ({
  page,
  context,
}, testInfo) => {
  const runtimeErrors: string[] = [];
  page.on("pageerror", (error) => runtimeErrors.push(error.message));
  const username = `ui_${Date.now()}_${Math.random().toString(16).slice(2, 8)}`;
  const password = "test-only-long-password";
  await page.goto("/register");
  await page.getByLabel("Username").fill(username);
  await page.getByLabel("Password", { exact: true }).fill(password);
  await page
    .getByRole("button", { name: "Create account", exact: true })
    .click();
  await expect(page.getByText("Registration request processed.")).toBeVisible();
  await page.getByRole("link", { name: "Continue to sign in" }).click();
  await page.getByLabel("Username").fill(username);
  await page.getByLabel("Password", { exact: true }).fill(password);
  const loginResponse = page.waitForResponse(
    (r) => r.url().endsWith("/api/auth") && r.request().method() === "POST",
  );
  await page.getByRole("button", { name: "Sign in to workspace" }).click();
  expect(await (await loginResponse).json()).toEqual({ username });
  await expect(
    page.getByRole("heading", { name: "Your next solution starts here." }),
  ).toBeVisible();
  const cookie = (await context.cookies()).find((c) =>
    ["codejudge-dev", "__Host-codejudge"].includes(c.name),
  );
  expect(cookie?.httpOnly).toBe(true);
  if (cookie?.name === "__Host-codejudge") expect(cookie.secure).toBe(true);
  expect(cookie?.sameSite).toBe("Strict");
  await page
    .getByRole("button", { name: "New challenge", exact: true })
    .click();
  await page
    .getByLabel("Title", { exact: true })
    .fill("A thoughtful Python challenge");
  await page
    .getByLabel("Problem description")
    .fill("Return the sum of two numbers. Keep the implementation simple.");
  await page
    .getByRole("button", { name: "Create challenge", exact: true })
    .click();
  await expect(
    page.getByRole("link", { name: /A thoughtful Python challenge/ }),
  ).toBeVisible();
  await page.screenshot({
    path: testInfo.outputPath("dashboard.png"),
    fullPage: true,
  });
  await page.route("**/api/backend/reviews/config", (route) =>
    route.fulfill({ status: 503, json: { detail: "temporarily unavailable" } }),
  );
  await page
    .getByRole("link", { name: /A thoughtful Python challenge/ })
    .click();
  await expect(
    page.getByRole("heading", { name: "A thoughtful Python challenge" }),
  ).toBeVisible();
  await expect(
    page.getByRole("region", { name: "Code review" }).getByRole("alert"),
  ).toContainText("may be waking up");
  await page.unroute("**/api/backend/reviews/config");
  await page
    .getByRole("button", { name: "Retry provider information" })
    .click();
  await expect(page.locator(".monaco-editor")).toBeVisible({ timeout: 60000 });
  await page.screenshot({
    path: testInfo.outputPath("editor.png"),
    fullPage: true,
  });
  await page
    .getByRole("button", { name: "Use accessible text editor" })
    .click();
  await page
    .getByRole("textbox", { name: "Python source code" })
    .fill("print(2 + 2)\n");
  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "Download", exact: true }).click();
  const downloaded = await download;
  const file = await downloaded.path();
  expect(await readFile(file!, "utf8")).toBe("print(2 + 2)\n");
  const reviewRequest = page.waitForRequest(
    (r) => r.url().endsWith("/api/backend/reviews") && r.method() === "POST",
  );
  await page.getByRole("button", { name: "Review code", exact: true }).click();
  await expect(page.getByText("Simulated · mock")).toBeVisible();
  await expect(page.getByText("Console output", { exact: true })).toBeVisible();
  await expect(page.getByText("Line 1", { exact: true })).toBeVisible();
  const reviewUrl = await page
    .getByRole("link", { name: "Open saved review" })
    .getAttribute("href");
  const sent = await reviewRequest;
  const requestKey = sent.headers()["idempotency-key"];
  expect(requestKey).toMatch(/^[0-9a-f-]{36}$/);
  const replay = await page.evaluate(
    async ({ body, key }) => {
      const response = await fetch("/api/backend/reviews", {
        method: "POST",
        headers: { "Content-Type": "application/json", "Idempotency-Key": key },
        body,
      });
      return { status: response.status, data: await response.json() };
    },
    { body: sent.postData()!, key: requestKey },
  );
  expect(replay.status).toBe(201);
  expect(reviewUrl).toBe(`/reviews/${replay.data.id}`);
  await page.screenshot({
    path: testInfo.outputPath("code-review.png"),
    fullPage: true,
  });
  await expect(
    page.getByRole("button", { name: "Request evaluation", exact: true }),
  ).toBeDisabled();
  await page.getByLabel("Existing artifact ID").fill("browser-test-artifact");
  await page.getByRole("checkbox").check();
  const submission = page.waitForRequest(
    (r) =>
      r.url().endsWith("/api/backend/evaluations") && r.method() === "POST",
  );
  await page
    .getByRole("button", { name: "Request evaluation", exact: true })
    .click();
  expect((await submission).postDataJSON()).toEqual({
    task_id: expect.any(String),
    submission_reference: "browser-test-artifact",
  });
  await expect(
    page.getByText(
      "The external runner is not configured. Your code was not executed.",
    ),
  ).toBeVisible({ timeout: 20000 });
  await expect(page.getByText("No score available")).toBeVisible();
  await page.screenshot({
    path: testInfo.outputPath("result.png"),
    fullPage: true,
  });
  const evaluationUrl = page.url();
  await page
    .getByRole("link", { name: "Evaluation history", exact: true })
    .last()
    .click();
  await expect(
    page.getByRole("heading", { name: "Your evaluation history." }),
  ).toBeVisible();
  await expect(page.getByText("Failed", { exact: true })).toBeVisible();
  const storage = await page.evaluate(() =>
    JSON.stringify({
      local: { ...localStorage },
      session: { ...sessionStorage },
      cookies: document.cookie,
    }),
  );
  expect(storage).not.toContain("access_token");
  expect(storage).not.toContain(password);
  expect(storage).not.toContain("codejudge-dev");
  expect(storage).not.toContain("__Host-codejudge");
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await page.reload();
  await expect(
    page.getByRole("heading", { name: "Your evaluation history." }),
  ).toBeVisible();
  await page.goto("/reviews");
  await expect(
    page.getByRole("heading", { name: "Your code reviews." }),
  ).toBeVisible();
  await page.getByRole("link", { name: /Simulated Python review/ }).click();
  await expect(page).toHaveURL(new RegExp(reviewUrl!));
  await expect(page.getByText("Console output", { exact: true })).toBeVisible();
  await page.reload();
  await expect(page.getByText("Simulated · mock")).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  expect(storage).not.toContain("print(2 + 2)");
  await page.screenshot({
    path: testInfo.outputPath("saved-review.png"),
    fullPage: true,
  });
  const crossOrigin = await fetch(
    new URL("/api/auth", testInfo.project.use.baseURL),
    {
      method: "POST",
      headers: {
        Origin: "https://evil.test",
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ action: "logout" }),
    },
  );
  expect(crossOrigin.status).toBe(403);
  const navigationToggle = page.getByRole("button", {
    name: "Open navigation",
  });
  if (await navigationToggle.isVisible()) {
    await navigationToggle.click();
    const drawer = page.getByRole("dialog", { name: "Workspace navigation" });
    await expect(
      drawer.getByRole("button", { name: "Close navigation" }),
    ).toBeFocused();
    await page.keyboard.press("Shift+Tab");
    await expect(
      drawer.getByRole("button", { name: "Sign out", exact: true }),
    ).toBeFocused();
    await page.keyboard.press("Tab");
    await expect(
      drawer.getByRole("button", { name: "Close navigation" }),
    ).toBeFocused();
    await page.keyboard.press("Escape");
    await expect(navigationToggle).toBeFocused();
    await navigationToggle.click();
  }
  await page.getByRole("button", { name: "Sign out", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Welcome back." }),
  ).toBeVisible();
  await page.goto(evaluationUrl);
  await expect(
    page.getByRole("heading", { name: "Welcome back." }),
  ).toBeVisible();
  await expect(page.getByRole("status")).toContainText("session has expired");
  expect(runtimeErrors).toEqual([]);
});
