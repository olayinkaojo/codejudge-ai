import type { HistoryEntry } from "./types";
const key = (username: string) => `codejudge:history:v1:${username}`;
export function readHistory(username: string): HistoryEntry[] {
  try {
    const data: unknown = JSON.parse(
      localStorage.getItem(key(username)) || "[]",
    );
    if (!Array.isArray(data)) return [];
    return data
      .filter(
        (v): v is HistoryEntry =>
          v &&
          typeof v.id === "string" &&
          /^[0-9a-f-]{36}$/i.test(v.id) &&
          typeof v.taskId === "string" &&
          typeof v.title === "string" &&
          typeof v.createdAt === "string",
      )
      .slice(0, 100);
  } catch {
    return [];
  }
}
export function remember(username: string, entry: HistoryEntry): boolean {
  try {
    localStorage.setItem(
      key(username),
      JSON.stringify(
        [
          entry,
          ...readHistory(username).filter((e) => e.id !== entry.id),
        ].slice(0, 100),
      ),
    );
    return true;
  } catch {
    return false;
  }
}
export function clearHistory(username: string) {
  try {
    localStorage.removeItem(key(username));
  } catch {
    /* Browsers can disable storage. */
  }
}
