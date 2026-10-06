/**
 * Browser-safe configuration. Server-only settings live in config.server.ts.
 *
 *   NEXT_PUBLIC_WS_URL  the API's WebSocket origin (wss in production); the
 *                       live socket cannot go through the Next/Vercel proxy.
 *
 * The localhost fallback exists only in development builds: NODE_ENV is
 * inlined at build time and the branch is removed from production bundles,
 * so a production build contains no localhost URL. Without NEXT_PUBLIC_WS_URL
 * a production build gets "" and the live socket fails visibly.
 */
export function publicWsOrigin(): string {
  const explicit = process.env.NEXT_PUBLIC_WS_URL;
  if (explicit) return explicit.replace(/\/$/, "");
  if (process.env.NODE_ENV !== "production") return "ws://localhost:8000";
  return "";
}
