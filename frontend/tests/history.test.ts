import { describe, expect, it, vi } from "vitest";
import { clearHistory, readHistory, remember } from "@/lib/history";
const entry = {
  id: "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
  taskId: "task",
  title: "Two Sum",
  createdAt: "2026-01-01",
};
describe("local history index", () => {
  it("isolates accounts, deduplicates IDs, and clears history", () => {
    remember("alice", entry);
    remember("alice", entry);
    expect(readHistory("alice")).toEqual([entry]);
    expect(readHistory("bob")).toEqual([]);
    clearHistory("alice");
    expect(readHistory("alice")).toEqual([]);
  });
  it("rejects malformed stored data", () => {
    localStorage.setItem("codejudge:history:v1:alice", "invalid");
    expect(readHistory("alice")).toEqual([]);
    localStorage.setItem("codejudge:history:v1:alice", '[{"id":"../../evil"}]');
    expect(readHistory("alice")).toEqual([]);
  });
  it("handles browsers that disable local storage", () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("disabled");
    });
    expect(remember("alice", entry)).toBe(false);
  });
});
