// @vitest-environment node
import { beforeEach, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
const mocks = vi.hoisted(() => ({ upstream: vi.fn(), destroy: vi.fn() }));
vi.mock("@/lib/session", () => ({
  session: async () => ({
    token: "server-only-token",
    expiresAt: Date.now() + 60000,
    destroy: mocks.destroy,
  }),
}));
vi.mock("@/lib/server", async (original) => ({
  ...(await original<typeof import("@/lib/server")>()),
  upstream: mocks.upstream,
}));
import { GET, POST } from "@/app/api/backend/[...path]/route";
beforeEach(() => {
  vi.clearAllMocks();
  vi.stubEnv("APP_ORIGIN", "http://localhost:3000");
});
const params = { params: Promise.resolve({ path: ["reviews"] }) };
it("forwards the replay key only after origin/session checks and preserves a bounded retry-after", async () => {
  const key = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee";
  mocks.upstream.mockResolvedValue(
    new Response('{"detail":"Usage limit reached"}', {
      status: 429,
      headers: { "Retry-After": "60" },
    }),
  );
  const response = await POST(
    new NextRequest("http://localhost:3000/api/backend/reviews", {
      method: "POST",
      headers: {
        Origin: "http://localhost:3000",
        "Content-Type": "application/json",
        "Idempotency-Key": key,
      },
      body: '{"source":"pass"}',
    }),
    params,
  );
  expect(mocks.upstream).toHaveBeenCalledWith(
    "/reviews",
    "POST",
    "server-only-token",
    { source: "pass" },
    key,
  );
  expect(response.headers.get("Retry-After")).toBe("60");
  expect(response.headers.get("Cache-Control")).toBe("no-store");
  expect(await response.text()).not.toContain("server-only-token");
});
it("rejects malformed replay headers and cross-origin writes before forwarding", async () => {
  for (const [origin, key, status] of [
    ["http://localhost:3000", "bad", 422],
    ["https://evil.test", "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee", 403],
  ] as const) {
    const response = await POST(
      new NextRequest("http://localhost:3000/api/backend/reviews", {
        method: "POST",
        headers: { Origin: origin, "Idempotency-Key": key },
      }),
      params,
    );
    expect(response.status).toBe(status);
  }
  expect(mocks.upstream).not.toHaveBeenCalled();
});
it("forwards only documented pagination and never a user-supplied backend target", async () => {
  mocks.upstream.mockResolvedValue(new Response("[]"));
  await GET(
    new NextRequest(
      "http://localhost:3000/api/backend/reviews?limit=2&offset=1&url=http://internal",
    ),
    params,
  );
  expect(mocks.upstream).toHaveBeenCalledWith(
    "/reviews?limit=2&offset=1",
    "GET",
    "server-only-token",
    undefined,
    undefined,
  );
});
