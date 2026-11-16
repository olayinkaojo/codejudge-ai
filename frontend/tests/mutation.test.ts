// @vitest-environment node
import { beforeEach, expect, it, vi } from "vitest";
import { createMutation } from "@/lib/mutation";
import { api } from "@/lib/client";
vi.mock("@/lib/client", () => ({ api: vi.fn() }));
beforeEach(() => vi.resetAllMocks());
it("coalesces simultaneous clicks and preserves replay key after uncertain failure", async () => {
  let reject!: (error: Error) => void;
  vi.mocked(api)
    .mockImplementationOnce(
      () =>
        new Promise((_, fail) => {
          reject = fail;
        }),
    )
    .mockResolvedValueOnce({ id: "saved" })
    .mockResolvedValueOnce({ id: "another" });
  const submit = createMutation();
  const first = submit("/reviews", { source: "pass" });
  const duplicate = submit("/reviews", { source: "pass" });
  reject(new Error("Connection interrupted"));
  await expect(first).rejects.toThrow();
  await expect(duplicate).rejects.toThrow();
  expect(api).toHaveBeenCalledTimes(1);
  const key = vi.mocked(api).mock.calls[0][1]?.headers;
  await submit("/reviews", { source: "pass" });
  expect(vi.mocked(api).mock.calls[1][1]?.headers).toEqual(key);
  await submit("/reviews", { source: "pass" });
  expect(vi.mocked(api).mock.calls[2][1]?.headers).not.toEqual(key);
});
it("uses a different key after editing the payload and stores nothing in browser storage", async () => {
  vi.mocked(api)
    .mockRejectedValueOnce(new Error("offline"))
    .mockResolvedValueOnce({});
  const submit = createMutation();
  await expect(submit("/reviews", { source: "one" })).rejects.toThrow();
  await submit("/reviews", { source: "two" });
  expect(vi.mocked(api).mock.calls[0][1]?.headers).not.toEqual(
    vi.mocked(api).mock.calls[1][1]?.headers,
  );
});
