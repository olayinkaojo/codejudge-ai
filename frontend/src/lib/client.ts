export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
  }
}
export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, {
      ...init,
      headers: { "Content-Type": "application/json", ...init?.headers },
      cache: "no-store",
      signal: init?.signal ?? AbortSignal.timeout(15000),
    });
  } catch {
    const mutation = init?.method && init.method !== "GET";
    throw new ApiError(
      mutation
        ? "Connection interrupted. Your request may have completed. Check history before retrying the unchanged request; no automatic retry was made."
        : "Unable to connect. Check your connection; the API may need a moment to wake up. Retry when ready.",
      0,
    );
  }
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    let message = "Something went wrong. Please try again.";
    if ([502, 503, 504].includes(response.status))
      message =
        "The API may be waking up or temporarily unavailable. Wait a moment and retry. For submissions, check history first; no automatic retry was made.";
    else if (typeof body.detail === "string") message = body.detail;
    else if (Array.isArray(body.detail))
      message = body.detail
        .map(
          (e: { loc?: string[]; msg?: string }) =>
            `${e.loc?.slice(1).join(".") || "Request"}: ${e.msg || "Invalid value"}`,
        )
        .join(" · ");
    const retry = Number(response.headers.get("Retry-After"));
    if (response.status === 429 && retry > 0 && retry <= 86400)
      message += ` Try again in ${retry} seconds.`;
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
  try {
    return await response.json();
  } catch {
    throw new ApiError(
      "The API response was interrupted. Check history before repeating a submission.",
      0,
    );
  }
}
export const backend = "/api/backend";
