import { randomBytes } from "node:crypto";
import { cookies } from "next/headers";
import { getIronSession } from "iron-session";
interface Session {
  token?: string;
  username?: string;
  expiresAt?: number;
}
const state = globalThis as typeof globalThis & {
  developmentSessionPassword?: string;
};
export async function session() {
  let password = process.env.SESSION_PASSWORD;
  if (!password || password.length < 32) {
    if (process.env.NODE_ENV === "production")
      throw new Error("SESSION_PASSWORD must contain at least 32 characters");
    password = state.developmentSessionPassword ??=
      randomBytes(32).toString("hex");
  }
  return getIronSession<Session>(await cookies(), {
    password,
    cookieName:
      process.env.NODE_ENV === "production"
        ? "__Host-codejudge"
        : "codejudge-dev",
    ttl: 86400 * 30,
    cookieOptions: {
      httpOnly: true,
      secure: process.env.NODE_ENV === "production",
      sameSite: "strict",
      path: "/",
    },
  });
}
