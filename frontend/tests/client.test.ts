// @vitest-environment node
import { afterEach, expect, it, vi } from "vitest";
import { api, ApiError } from "@/lib/client";
afterEach(() => vi.unstubAllGlobals());
it("bounds browser requests without automatically retrying", async () => {
  const fetcher = vi
    .fn()
    .mockRejectedValue(
      new DOMException("private host details", "TimeoutError"),
    );
  vi.stubGlobal("fetch", fetcher);
  await expect(
    api("/api/backend/reviews", { method: "POST" }),
  ).rejects.toMatchObject({
    status: 0,
    message: expect.stringContaining("may have completed"),
  });
  expect(fetcher).toHaveBeenCalledTimes(1);
  expect(fetcher).toHaveBeenCalledWith(
    "/api/backend/reviews",
    expect.objectContaining({
      signal: expect.any(AbortSignal),
      cache: "no-store",
    }),
  );
});
it("explains cold starts and bounded retry-after without leaking backend diagnostics", async () => {
  vi.stubGlobal(
    "fetch",
    vi
      .fn()
      .mockResolvedValueOnce(
        new Response('{"detail":"private database error"}', { status: 503 }),
      )
      .mockResolvedValueOnce(
        new Response('{"detail":"Usage limit reached"}', {
          status: 429,
          headers: { "Retry-After": "60" },
        }),
      ),
  );
  await expect(api("/api/backend/tasks")).rejects.toThrow("may be waking up");
  await expect(api("/api/backend/reviews")).rejects.toThrow(
    "Try again in 60 seconds",
  );
});
it("reports offline reads with a recoverable message", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockRejectedValue(new TypeError("Failed to fetch")),
  );
  await expect(api("/api/backend/tasks")).rejects.toBeInstanceOf(ApiError);
});
