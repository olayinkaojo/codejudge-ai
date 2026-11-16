import { defineConfig, devices } from "@playwright/test";
const base = new URL(process.env.E2E_BASE_URL || "http://localhost:3000");
for (const target of [
  base,
  new URL(process.env.BACKEND_URL || "http://127.0.0.1:8000"),
]) {
  if (
    target.protocol !== "http:" ||
    !["localhost", "127.0.0.1"].includes(target.hostname) ||
    target.username ||
    target.password
  )
    throw new Error(
      "Browser tests create records: use loopback HTTP frontend/backend URLs only.",
    );
}
export default defineConfig({
  testDir: "./e2e",
  timeout: 90000,
  expect: { timeout: 15000 },
  fullyParallel: false,
  workers: 1,
  use: {
    baseURL: base.origin,
    trace: "retain-on-failure",
    ...(process.env.PLAYWRIGHT_CHROMIUM_PATH
      ? {
          launchOptions: {
            executablePath: process.env.PLAYWRIGHT_CHROMIUM_PATH,
          },
        }
      : {}),
  },
  webServer: {
    env: { APP_ORIGIN: base.origin },
    command: `npm run dev -- --hostname 0.0.0.0 --port ${base.port || "80"}`,
    url: `${base.origin}/login`,
    reuseExistingServer: !process.env.CI,
    timeout: 120000,
  },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"] } },
    {
      name: "tablet",
      use: {
        ...devices["Desktop Chrome"],
        viewport: { width: 768, height: 1024 },
      },
    },
    {
      name: "mobile",
      use: { ...devices["iPhone 13"], browserName: "chromium" },
    },
  ],
});
