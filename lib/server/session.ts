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

/**
 * `resolved` is false when the backend did not answer (timeout, network
 * error, 5xx): "nobody is signed in" and "the API is waking up" must not look
 * the same, or a serverless cold start would render a signed-in user as
 * signed out with nothing to correct it. Unresolved, the client asks again.
 */
export async function getServerUser(): Promise<{ user: SessionUser | null; resolved: boolean }> {
  // Frontend-only deployment (BACKEND_ORIGIN=none): nobody can be signed in.
  if (!backendConnected()) return { user: null, resolved: true };
  const jar = await cookies();
  // Only a session cookie can make anyone signed in. Any other cookie (the
  // cookie-consent choice, say) must not cost every page render a round trip
  // to the API just to hear "401".
  if (!jar.get("rs_session")?.value) return { user: null, resolved: true };
  const cookieHeader = jar.toString();

  try {
    // A short timeout: a hung backend must not hold the page render open.
    // A warm API answers in well under 100 ms from here; one waking from idle
    // takes several seconds, and then the page is better shown at once and
    // the session confirmed by the browser (AuthProvider) than held blank.
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 1500);
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
    // 401/403: a definite "not signed in". Anything else non-OK: no answer.
    if (response.status === 401 || response.status === 403) return { user: null, resolved: true };
    if (!response.ok) return { user: null, resolved: false };

    // The body can be empty when the API is mid-restart; parsing it
    // unguarded throws "Unexpected end of JSON input" and 500s the page.
    const body = (await response.json().catch(() => null)) as { user?: SessionUser } | null;
    return body?.user ? { user: body.user, resolved: true } : { user: null, resolved: false };
  } catch {
    // Backend unreachable or slow to wake: let the client ask again rather
    // than declaring the visitor signed out.
    return { user: null, resolved: false };
  }
}
