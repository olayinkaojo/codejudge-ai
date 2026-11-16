// @vitest-environment node
import { describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
import { allowed } from "@/lib/proxy-policy";
import { readBody, sameOrigin, upstream } from "@/lib/server";
describe("proxy boundary", () => {
  it("only forwards documented routes and methods", () => {
    expect(allowed("tasks", "GET")).toBe(true);
    expect(allowed("evaluations", "POST")).toBe(true);
    expect(allowed("evaluations", "GET")).toBe(false);
    expect(allowed("auth/token", "GET")).toBe(false);
    expect(allowed("../auth/token", "POST")).toBe(false);
    expect(allowed("tasks", "DELETE")).toBe(false);
  });
  it("requires an exact trusted origin for mutations", () => {
    vi.stubEnv("APP_ORIGIN", "http://localhost:3000");
    expect(
      sameOrigin(
        new NextRequest("http://localhost:3000/api/auth", {
          headers: { Origin: "https://evil.test" },
        }),
      ),
    ).toBe(false);
    expect(sameOrigin(new NextRequest("http://localhost:3000/api/auth"))).toBe(
      false,
    );
    expect(
      sameOrigin(
        new NextRequest("http://localhost:3000/api/auth", {
          headers: { Origin: "http://localhost:3000" },
        }),
      ),
    ).toBe(true);
  });
  it("bounds streamed JSON input", async () => {
    const req = new NextRequest("http://localhost/api", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ value: "a".repeat(131073) }),
    });
    await expect(readBody(req)).rejects.toThrow("Request too large");
  });
  it("refuses backend URLs with credentials", async () => {
    vi.stubEnv("BACKEND_URL", "https://user:pass@host");
    await expect(upstream("/tasks")).rejects.toThrow("Invalid BACKEND_URL");
  });
  it("only adds bearer authorization on the server and disables redirects/cache", async () => {
    vi.stubEnv("BACKEND_URL", "http://localhost:8000");
    const fetcher = vi.fn().mockResolvedValue(new Response("{}"));
    vi.stubGlobal("fetch", fetcher);
    await upstream("/tasks", "GET", "server-only-token");
    expect(fetcher).toHaveBeenCalledWith(
      new URL("http://localhost:8000/tasks"),
      expect.objectContaining({
        cache: "no-store",
        redirect: "error",
        headers: expect.objectContaining({
          Authorization: "Bearer server-only-token",
        }),
      }),
    );
  });
});
