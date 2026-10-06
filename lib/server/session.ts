import { cookies } from "next/headers";
import type { SessionUser } from "@/lib/auth";
import { backendConnected, backendOrigin } from "@/lib/config.server";

/**
 * Resolve the signed-in user on the server, for the first paint.
 *
 * The workspace renders the right chrome immediately instead of flashing a
 * signed-out shell while a client fetch resolves. This forwards the caller's
 * own cookie and asks the backend, so the answer is the backend's, not a
 * claim decoded from an unverified token.
 */
const BACKEND_ORIGIN = backendOrigin();

export async function getServerUser(): Promise<SessionUser | null> {
  // Frontend-only deployment (BACKEND_ORIGIN=none): nobody can be signed in.
  if (!backendConnected()) return null;
  const jar = await cookies();
  const cookieHeader = jar.toString();
  if (!cookieHeader) return null;

  try {
    // A short timeout: a hung backend must not hold the page render open.
    // Without this a restarting API stalls every server-rendered request.
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 3000);
    let response: Response;
    try {
      response = await fetch(`${BACKEND_ORIGIN}/api/auth/me`, {
        headers: { cookie: cookieHeader },
        cache: "no-store",
        signal: controller.signal,
      });
    } finally {
      clearTimeout(timer);
    }
    if (!response.ok) return null;

    // The body can be empty when the API is mid-restart; parsing it
    // unguarded throws "Unexpected end of JSON input" and 500s the page.
    const body = (await response.json().catch(() => null)) as { user?: SessionUser } | null;
    return body?.user ?? null;
  } catch {
    // Backend unreachable: render as signed out rather than failing the page.
    // Protected data is fetched separately and will report its own state.
    return null;
  }
}
