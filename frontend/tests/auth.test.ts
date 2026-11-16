// @vitest-environment node
import { beforeEach, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
const mocks = vi.hoisted(() => ({
  state: {
    token: undefined as string | undefined,
    username: undefined as string | undefined,
    expiresAt: undefined as number | undefined,
    save: vi.fn(),
    destroy: vi.fn(),
  },
  upstream: vi.fn(),
}));
vi.mock("@/lib/session", () => ({ session: async () => mocks.state }));
vi.mock("@/lib/server", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/server")>()),
  upstream: mocks.upstream,
}));
import { GET, POST } from "@/app/api/auth/route";
beforeEach(() => {
  mocks.state.token = undefined;
  mocks.state.expiresAt = undefined;
  vi.stubEnv("APP_ORIGIN", "http://localhost:3000");
  mocks.upstream.mockReset();
});
const request = (body: unknown) =>
  new NextRequest("http://localhost:3000/api/auth", {
    method: "POST",
    headers: {
      Origin: "http://localhost:3000",
      "Content-Type": "application/json",
    },
    body: JSON.stringify(body),
  });
it("stores token server-side and never returns it to the browser", async () => {
  mocks.upstream.mockResolvedValue(
    new Response(
      JSON.stringify({ access_token: "private-token", expires_in: 3600 }),
    ),
  );
  const result = await POST(
    request({
      action: "login",
      username: "ALICE",
      password: "not-a-real-credential",
    }),
  );
  expect(await result.json()).toEqual({ username: "alice" });
  expect(mocks.state.token).toBe("private-token");
  expect(mocks.state.save).toHaveBeenCalled();
});
it("does not turn registration into a fictitious login", async () => {
  mocks.upstream.mockResolvedValue(new Response("{}", { status: 201 }));
  const result = await POST(
    request({
      action: "register",
      username: "alice",
      password: "not-a-real-credential",
    }),
  );
  expect(result.status).toBe(201);
  expect(mocks.state.token).toBeUndefined();
});
it("rejects unauthenticated and expired sessions", async () => {
  expect((await GET()).status).toBe(401);
  mocks.state.token = "expired";
  mocks.state.expiresAt = 1;
  expect((await GET()).status).toBe(401);
});
it("does not claim logout succeeded when revocation failed", async () => {
  mocks.state.token = "token";
  mocks.upstream.mockResolvedValue(new Response("{}", { status: 503 }));
  expect((await POST(request({ action: "logout" }))).status).toBe(503);
});
it("rejects missing origin before contacting the backend", async () => {
  const result = await POST(
    new NextRequest("http://localhost:3000/api/auth", {
      method: "POST",
      body: "{}",
    }),
  );
  expect(result.status).toBe(403);
  expect(mocks.upstream).not.toHaveBeenCalled();
});
it("returns a precise error for malformed JSON", async () => {
  const response = await POST(
    new NextRequest("http://localhost:3000/api/auth", {
      method: "POST",
      headers: {
        Origin: "http://localhost:3000",
        "Content-Type": "application/json",
      },
      body: "{",
    }),
  );
  expect(response.status).toBe(400);
});
it("rejects oversized auth bodies", async () => {
  expect(
    (await POST(request({ action: "login", password: "x".repeat(131073) })))
      .status,
  ).toBe(413);
});
it("requires JSON content type", async () => {
  const response = await POST(
    new NextRequest("http://localhost:3000/api/auth", {
      method: "POST",
      headers: { Origin: "http://localhost:3000" },
      body: "not-json",
    }),
  );
  expect(response.status).toBe(415);
});
it("rejects malformed backend expiry and never saves the session", async () => {
  mocks.state.save.mockClear();
  mocks.upstream.mockResolvedValue(
    new Response(JSON.stringify({ access_token: "token", expires_in: -1 })),
  );
  expect(
    (
      await POST(
        request({
          action: "login",
          username: "alice",
          password: "test-only-password",
        }),
      )
    ).status,
  ).toBe(503);
  expect(mocks.state.save).not.toHaveBeenCalled();
});
