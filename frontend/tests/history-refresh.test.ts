import { expect, it, vi } from "vitest";
import { fetchHistory } from "@/components/evaluation";
import { api } from "@/lib/client";
vi.mock("next/navigation", () => ({
  useRouter: vi.fn(),
  usePathname: vi.fn(),
}));
vi.mock("@/lib/client", () => ({ api: vi.fn(), backend: "/api/backend" }));
vi.mock("@/lib/history", () => ({
  readHistory: () =>
    Array.from({ length: 30 }, (_, i) => ({
      id: String(i),
      title: `Task ${i}`,
    })),
}));
it("pauses history fan-out after an unavailable batch instead of timing out all 30 records", async () => {
  vi.mocked(api).mockRejectedValue({ status: 503, message: "API waking up" });
  const data = await fetchHistory("alice");
  expect(api).toHaveBeenCalledTimes(5);
  expect(Object.keys(data.errors)).toHaveLength(30);
  expect(data.errors["29"]).toContain("Refresh paused");
});
