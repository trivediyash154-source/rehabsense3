import type { NextConfig } from "next";

/**
 * Security headers are conservative on purpose: this prototype loads no
 * third-party scripts, fonts are self-hosted at build time by next/font,
 * and no analytics vendor is embedded in the client.
 */
const securityHeaders = [
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=(), interest-cohort=()" },
  { key: "Cross-Origin-Opener-Policy", value: "same-origin" },
];

/**
 * The backend's origin, used only on the server. It is deliberately not a
 * `NEXT_PUBLIC_` variable: the browser never calls the backend directly for
 * REST, it calls this app's own `/api/*`, which is proxied below.
 *
 * Proxying is what makes the session cookie first-party. A cross-origin
 * cookie would need `SameSite=None`, which is exactly the setting that lets
 * any site send it; same-origin lets us keep `SameSite=Lax` and `HttpOnly`,
 * and lets middleware read the session server-side.
 */
const BACKEND_ORIGIN =
  process.env.BACKEND_ORIGIN ?? process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  async headers() {
    return [{ source: "/:path*", headers: securityHeaders }];
  },
  async rewrites() {
    return {
      // `afterFiles` means this app's own route handlers (/api/contact,
      // /api/events) still win; everything else under /api falls through to
      // the backend.
      beforeFiles: [],
      afterFiles: [{ source: "/api/:path*", destination: `${BACKEND_ORIGIN}/api/:path*` }],
      fallback: [],
    };
  },
};

export default nextConfig;
