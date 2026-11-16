import { api } from "./client";

// Keep replay state only in memory. A reload never persists source or credentials.
export function createMutation() {
  let previous: { body: string; key: string } | undefined;
  let active: Promise<unknown> | undefined;
  return async function submit<T>(path: string, value: unknown): Promise<T> {
    if (active) return active as Promise<T>;
    const body = JSON.stringify(value);
    if (!previous || previous.body !== body)
      previous = { body, key: crypto.randomUUID() };
    active = api<T>(path, {
      method: "POST",
      body,
      headers: { "Idempotency-Key": previous.key },
    });
    try {
      const result = (await active) as T;
      previous = undefined;
      return result;
    } finally {
      active = undefined;
    }
  };
}
