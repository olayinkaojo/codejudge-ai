export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
  }
}
export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
    cache: "no-store",
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    let message = "Something went wrong. Please try again.";
    if (typeof body.detail === "string") message = body.detail;
    else if (Array.isArray(body.detail))
      message = body.detail
        .map(
          (e: { loc?: string[]; msg?: string }) =>
            `${e.loc?.slice(1).join(".") || "Request"}: ${e.msg || "Invalid value"}`,
        )
        .join(" · ");
    if (
      response.status === 401 &&
      typeof window !== "undefined" &&
      !path.startsWith("/api/auth")
    )
      window.location.replace(
        new URL("/login?expired=1", window.location.origin),
      );
    throw new ApiError(message, response.status);
  }
  if (response.status === 204) return undefined as T;
  return response.json();
}
export const backend = "/api/backend";
