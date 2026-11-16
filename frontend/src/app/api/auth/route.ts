import { NextRequest } from "next/server";
import { session } from "@/lib/session";
import { BodyError, json, readBody, sameOrigin, upstream } from "@/lib/server";
export const runtime = "nodejs";
export async function GET() {
  try {
    const s = await session();
    if (!s.token || !s.expiresAt || s.expiresAt <= Date.now()) {
      s.destroy();
      return json({ detail: "Sign in to continue." }, 401);
    }
    const check = await upstream("/tasks?limit=1", "GET", s.token);
    if (check.status === 401) {
      s.destroy();
      return json({ detail: "Your session has expired. Sign in again." }, 401);
    }
    if (!check.ok)
      return json({ detail: "The backend is unavailable. Please retry." }, 503);
    return json({ username: s.username });
  } catch (error) {
    if (error instanceof BodyError)
      return json({ detail: error.message }, error.status);
    return json({ detail: "Unable to connect to the backend." }, 503);
  }
}
export async function POST(request: NextRequest) {
  if (!sameOrigin(request))
    return json({ detail: "Invalid request origin." }, 403);
  try {
    const input = (await readBody(request)) as {
      action?: string;
      username?: string;
      password?: string;
    };
    if (!input || !["login", "register", "logout"].includes(input.action || ""))
      return json({ detail: "Invalid action." }, 400);
    const s = await session();
    if (input.action === "logout") {
      if (s.token) {
        const response = await upstream("/auth/token", "DELETE", s.token);
        if (!response.ok && response.status !== 401)
          return json(
            { detail: "Could not revoke the session. Please retry." },
            503,
          );
      }
      s.destroy();
      return json({ ok: true });
    }
    if (
      typeof input.username !== "string" ||
      typeof input.password !== "string"
    )
      return json({ detail: "Username and password are required." }, 422);
    const credentials = { username: input.username, password: input.password };
    const response = await upstream(
      input.action === "register" ? "/auth/register" : "/auth/token",
      "POST",
      undefined,
      credentials,
    );
    const data = await response.json();
    if (!response.ok) return json(data, response.status);
    if (input.action === "register") return json({ ok: true }, 201);
    if (
      typeof data.access_token !== "string" ||
      !data.access_token ||
      data.access_token.length > 256 ||
      typeof data.expires_in !== "number" ||
      !Number.isFinite(data.expires_in) ||
      data.expires_in < 1 ||
      data.expires_in > 2592000
    )
      throw new Error("Invalid login response");
    s.token = data.access_token;
    s.username = input.username.trim().toLowerCase();
    s.expiresAt = Date.now() + data.expires_in * 1000;
    await s.save();
    return json({ username: s.username });
  } catch (error) {
    if (error instanceof BodyError)
      return json({ detail: error.message }, error.status);
    return json(
      {
        detail:
          "Unable to process your request. Check your connection and try again.",
      },
      503,
    );
  }
}
