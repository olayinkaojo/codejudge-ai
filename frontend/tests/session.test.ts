// @vitest-environment node
import { expect, it, vi } from "vitest";
const set = vi.hoisted(() => vi.fn());
vi.mock("next/headers", () => ({
  cookies: async () => ({ get: () => undefined, set }),
}));
import { session } from "@/lib/session";
it("encrypts bearer tokens inside a host-only secure HttpOnly cookie in production", async () => {
  vi.stubEnv("NODE_ENV", "production");
  vi.stubEnv("SESSION_PASSWORD", "test-key-".repeat(8));
  const s = await session();
  s.token = "sensitive-bearer-value";
  s.username = "alice";
  s.expiresAt = Date.now() + 3600000;
  await s.save();
  expect(set).toHaveBeenCalledWith(
    "__Host-codejudge",
    expect.any(String),
    expect.objectContaining({
      httpOnly: true,
      secure: true,
      sameSite: "strict",
      path: "/",
    }),
  );
  expect(set.mock.calls[0][1]).not.toContain("sensitive-bearer-value");
});
it("fails closed without a production session key", async () => {
  vi.stubEnv("NODE_ENV", "production");
  vi.stubEnv("SESSION_PASSWORD", "");
  await expect(session()).rejects.toThrow("SESSION_PASSWORD");
});
