/**
 * Server-only configuration (next.config, middleware, route handlers, server
 * components). Never imported by browser code, so nothing here -- including
 * the development localhost defaults -- reaches the client bundle.
 *
 *   BACKEND_ORIGIN       where Next proxies /api/* and the server session check goes;
 *                        the literal `none` declares a frontend-only deployment
 *   NEXT_PUBLIC_SITE_URL canonical site origin for metadata (on Vercel it
 *                        defaults to the project's production domain)
 *
 * On Vercel (VERCEL=1 / VERCEL_ENV set) `assertDeploymentConfig()` fails the
 * build if a required URL is missing, not https/wss, or local.
 */

type Env = Record<string, string | undefined>;

const DEV_API = "http://localhost:8000";
const DEV_SITE = "http://localhost:3000";

/**
 * False only when the deployment explicitly declares `BACKEND_ORIGIN=none`:
 * the frontend is live but no RehabSense API exists for it yet. Then /api/*
 * answers 503 BACKEND_NOT_CONNECTED (app/backend-unavailable) and the UI shows
 * the labelled demo data. An unset BACKEND_ORIGIN is never treated this way:
 * on Vercel it still fails the build.
 */
export function backendConnected(env: Env = process.env): boolean {
  return (env.BACKEND_ORIGIN ?? "").trim().toLowerCase() !== "none";
}

export function backendOrigin(): string {
  return (process.env.BACKEND_ORIGIN ?? DEV_API).replace(/\/$/, "");
}

/**
 * `VERCEL_PROJECT_PRODUCTION_URL` is a Vercel system variable (build and
 * runtime): the project's shortest production domain, custom if one exists.
 * Previews therefore point their canonical URL at production, as they should.
 */
export function siteUrl(env: Env = process.env): string {
  if (env.NEXT_PUBLIC_SITE_URL) return env.NEXT_PUBLIC_SITE_URL.replace(/\/$/, "");
  if (env.VERCEL_PROJECT_PRODUCTION_URL) return `https://${env.VERCEL_PROJECT_PRODUCTION_URL}`;
  return DEV_SITE;
}

export function assertDeploymentConfig(env: Env = process.env): void {
  if (!(env.VERCEL === "1" || env.VERCEL_ENV)) return;
  const problems: string[] = [];
  const need = (name: string, scheme: RegExp, hint: string) => {
    const v = env[name];
    if (!v) problems.push(`${name} is not set (${hint})`);
    else if (!scheme.test(v)) problems.push(`${name}=${v} must match ${scheme} (${hint})`);
    else if (/localhost|127\.0\.0\.1|0\.0\.0\.0/.test(v)) problems.push(`${name} points at a local address`);
  };
  const connected = backendConnected(env);
  if (connected) {
    need("BACKEND_ORIGIN", /^https:\/\//,
      "the RehabSense API, e.g. https://api.example.com -- or the literal `none` to deploy the frontend without an API");
    need("NEXT_PUBLIC_WS_URL", /^wss:\/\//, "the API's WebSocket origin, e.g. wss://api.example.com");
  }
  if (env.NEXT_PUBLIC_SITE_URL || !env.VERCEL_PROJECT_PRODUCTION_URL) {
    need("NEXT_PUBLIC_SITE_URL", /^https:\/\//, "this site's origin, e.g. https://rehabsense.vercel.app");
  }
  if (problems.length) {
    throw new Error(`RehabSense deployment configuration invalid:\n  - ${problems.join("\n  - ")}`);
  }
  if (!connected) {
    console.warn(
      "RehabSense: BACKEND_ORIGIN=none -- FRONTEND-ONLY deployment. /api/* answers 503 " +
        "BACKEND_NOT_CONNECTED; sign-in, patients, sessions and live data are unavailable " +
        "and the UI says so. Set BACKEND_ORIGIN and NEXT_PUBLIC_WS_URL once the API is hosted.",
    );
  }
}
