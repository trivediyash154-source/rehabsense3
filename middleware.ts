import { NextResponse, type NextFetchEvent, type NextRequest } from "next/server";

/**
 * Route protection at the edge, before any workspace page renders.
 *
 * This runs on the server, so an unauthenticated visitor is redirected rather
 * than briefly seeing a page that a client-side check would hide afterwards.
 *
 * It is a routing guard, not the authorization boundary: the signature is
 * never checked here, because that would mean shipping the backend's secret
 * into the edge runtime. Every API response is authorised server-side against
 * the real session, so a forged cookie gets an empty workspace and 401s, never
 * someone else's data.
 */
const SESSION_COOKIE = "rs_session";

/**
 * `/dashboard` is deliberately absent: it is the public, clearly-labelled
 * illustrative demo that the auth screens link to as "Explore without an
 * account". Protecting it would send that link straight back to /login.
 */
const PROTECTED = ["/workspace"];

/** Signed-in users have no reason to see these. */
const AUTH_PAGES = ["/login", "/signup"];

/**
 * Is this cookie a session that has not yet expired?
 *
 * Presence alone is not enough. An expired token still *exists* in the
 * browser, and treating it as a session traps the user completely: the guard
 * below bounces them off /login as "already signed in", while every API call
 * behind that cookie returns 401, so the workspace loads with no data and
 * there is no route back to the sign-in form. Reloading never clears it,
 * because the stale cookie is what causes the redirect.
 *
 * Reading `exp` needs no secret -- a JWT payload is base64url, not encrypted.
 * That is safe precisely because this decides routing only; authorization
 * still happens in the backend against a verified signature.
 */
function hasLiveSession(token: string | undefined): boolean {
  if (!token) return false;

  const segments = token.split(".");
  if (segments.length !== 3) return false;

  try {
    const base64 = segments[1].replace(/-/g, "+").replace(/_/g, "/");
    const padded = base64 + "=".repeat((4 - (base64.length % 4)) % 4);
    const claims = JSON.parse(atob(padded)) as { exp?: unknown };

    if (typeof claims.exp !== "number") return false;
    // A little skew tolerance so a clock a few seconds fast does not sign the
    // user out mid-request.
    return claims.exp * 1000 > Date.now() - 30_000;
  } catch {
    // Malformed, truncated or not a JWT at all: not a session.
    return false;
  }
}

/**
 * Start waking the API the moment someone opens a sign-in page.
 *
 * The API scales to zero after five idle minutes and takes several seconds to
 * start again. The browser's own check only runs after the page has loaded
 * and hydrated; asking here, at the edge, starts the API's boot seconds
 * earlier. Fire-and-forget (waitUntil): the page never waits for it, and the
 * sign-in form still reports the real state from its own check.
 */
function wakeApi(event: NextFetchEvent) {
  const origin = process.env.BACKEND_ORIGIN;
  if (!origin || origin === "none") return;
  event.waitUntil(
    fetch(`${origin.replace(/\/$/, "")}/api/auth/providers`, { cache: "no-store" }).then(
      () => undefined,
      () => undefined,
    ),
  );
}

export function middleware(request: NextRequest, event: NextFetchEvent) {
  const { pathname, search } = request.nextUrl;
  const token = request.cookies.get(SESSION_COOKIE)?.value;
  const signedIn = hasLiveSession(token);
  // A cookie that is present but no longer usable. It has to be actively
  // cleared, otherwise it keeps driving the redirect that hides /login.
  const staleCookie = Boolean(token) && !signedIn;

  if (PROTECTED.some((p) => pathname === p || pathname.startsWith(`${p}/`))) {
    if (!signedIn) {
      const login = new URL("/login", request.url);
      // Preserved so the user returns to the page they actually wanted.
      login.searchParams.set("next", `${pathname}${search}`);
      const response = NextResponse.redirect(login);
      response.headers.set(
        "x-rehabsense-redirect",
        staleCookie ? "session-expired" : "unauthenticated",
      );
      if (staleCookie) response.cookies.delete(SESSION_COOKIE);
      return response;
    }
  }

  if (AUTH_PAGES.includes(pathname)) {
    if (!signedIn) wakeApi(event);
    if (signedIn) {
      return NextResponse.redirect(new URL("/workspace", request.url));
    }
    if (staleCookie) {
      // Let the sign-in form render, but drop the dead cookie on the way so
      // the next navigation starts from a clean state.
      const response = NextResponse.next();
      response.cookies.delete(SESSION_COOKIE);
      response.headers.set("x-rehabsense-redirect", "session-expired");
      return response;
    }
  }

  return NextResponse.next();
}

export const config = {
  matcher: ["/workspace/:path*", "/login", "/signup"],
};
