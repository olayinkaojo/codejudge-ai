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
    if (path === "tasks" && request.method === "GET")
      for (const name of ["limit", "offset"]) {
        const value = request.nextUrl.searchParams.get(name);
        if (value !== null) query.set(name, value);
      }
    const response = await upstream(
      `/${path}${query.size ? `?${query}` : ""}`,
      request.method,
      s.token,
      request.method === "POST" ? await readBody(request) : undefined,
    );
    if (response.status === 401) s.destroy();
    if (response.status === 204) return new NextResponse(null, { status: 204 });
    return json(await response.json(), response.status);
  } catch (error) {
    if (error instanceof BodyError)
      return json({ detail: error.message }, error.status);
    return json(
      { detail: "The backend is unavailable. Please try again." },
      503,
    );
  }
}
export { handle as GET, handle as POST };
