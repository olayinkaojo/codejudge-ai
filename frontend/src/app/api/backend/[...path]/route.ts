import { NextRequest, NextResponse } from "next/server";
import { session } from "@/lib/session";
import { BodyError, json, readBody, sameOrigin, upstream } from "@/lib/server";
export const runtime = "nodejs";
import { allowed } from "@/lib/proxy-policy";
async function handle(
  request: NextRequest,
  context: { params: Promise<{ path: string[] }> },
) {
  const path = (await context.params).path.join("/");
  if (!allowed(path, request.method))
    return json({ detail: "Resource not found." }, 404);
  if (request.method !== "GET" && !sameOrigin(request))
    return json({ detail: "Invalid request origin." }, 403);
  try {
    const s = await session();
    if (!s.token || !s.expiresAt || s.expiresAt <= Date.now()) {
      s.destroy();
      return json({ detail: "Your session has expired. Sign in again." }, 401);
    }
    const query = new URLSearchParams();
    if (["tasks", "reviews"].includes(path) && request.method === "GET")
      for (const name of ["limit", "offset"]) {
        const value = request.nextUrl.searchParams.get(name);
        if (value !== null) query.set(name, value);
      }
    const requestId =
      request.method === "POST" ? request.headers.get("Idempotency-Key") : null;
    if (
      requestId &&
      !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(
        requestId,
      )
    )
      return json({ detail: "Invalid request key." }, 422);
    const response = await upstream(
      `/${path}${query.size ? `?${query}` : ""}`,
      request.method,
      s.token,
      request.method === "POST" ? await readBody(request) : undefined,
      requestId || undefined,
    );
    if (response.status === 401) s.destroy();
    if (response.status === 204) return new NextResponse(null, { status: 204 });
    const retry = response.headers.get("Retry-After");
    return json(
      await response.json(),
      response.status,
      retry && /^\d{1,6}$/.test(retry) ? { "Retry-After": retry } : {},
    );
  } catch (error) {
    if (error instanceof BodyError)
      return json({ detail: error.message }, error.status);
    return json(
      {
        detail:
          "The API may be waking up or unavailable. Check your connection. For a submission, check history before retrying the unchanged request.",
      },
      503,
    );
  }
}
export { handle as GET, handle as POST };
