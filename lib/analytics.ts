import { hasConsent } from "@/lib/consent";

/**
 * Product event logging with a strict allowlist.
 *
 * Design rule: an event may only ever carry values that already appear in this
 * file. Free-form strings, form contents, credentials, verification codes,
 * tokens and identifiers are structurally impossible to send — `sanitize`
 * drops anything that is not an allowlisted key with an allowlisted value.
 */

export const eventNames = [
  "page_view",
  "theme_changed",
  "hero_cta_clicked",
  "demo_requested",
  "contact_started",
  "contact_submitted",
  "contact_failed",
  "login_started",
  "login_succeeded",
  "login_failed",
  "signup_started",
  "signup_succeeded",
  "social_auth_started",
  "phone_verification_started",
  "phone_verification_succeeded",
  "password_reset_requested",
  "verification_code_requested",
  "error_occurred",
] as const;

export type EventName = (typeof eventNames)[number];

export const routeAllowlist = [
  "/",
  "/login",
  "/signup",
  "/forgot-password",
  "/verify-phone",
  "/verify-email",
  "/contact",
  "/dashboard",
] as const;

export const actionAllowlist = [
  "explore_system",
  "hero",
  "nav",
  "delivered",
  "login",
  "signup",
  "forgot-password",
  "verify-phone",
  "verify-email",
  "resend",
] as const;

export const providerAllowlist = ["google", "facebook", "phone", "email"] as const;

/** Roles are a coarse category, not personal data. */
export const roleAllowlist = ["PATIENT", "PHYSIOTHERAPIST", "TECHNICIAN", "ADMIN"] as const;

export const codeAllowlist = [
  "AUTH_NOT_CONFIGURED",
  // Error codes returned by the real auth API. Codes only — never the
  // message, which can quote user input.
  "UNAUTHORIZED",
  "FORBIDDEN",
  "VALIDATION_ERROR",
  "EMAIL_ALREADY_REGISTERED",
  "NETWORK_ERROR",
  "API_UNREACHABLE",
  "BACKEND_NOT_CONNECTED",
  "ERROR",
  "CONTACT_NOT_CONFIGURED",
  "CONTACT_DELIVERY_FAILED",
  "CONTACT_RATE_LIMITED",
  "WEBGL_UNAVAILABLE",
] as const;

export type SafeProperties = {
  route?: (typeof routeAllowlist)[number];
  theme?: Theme;
  action?: (typeof actionAllowlist)[number];
  provider?: (typeof providerAllowlist)[number];
  code?: (typeof codeAllowlist)[number];
  role?: (typeof roleAllowlist)[number];
};

type Theme = "dark" | "light";

export type AnalyticsEvent = {
  name: EventName;
  at: string;
  properties: SafeProperties;
};

export interface AnalyticsAdapter {
  send(event: AnalyticsEvent): void | Promise<void>;
}

/** Drops any property whose value is not on its allowlist. */
function sanitize(properties: SafeProperties): SafeProperties {
  const output: SafeProperties = {};
  if (properties.route && (routeAllowlist as readonly string[]).includes(properties.route)) {
    output.route = properties.route;
  }
  if (properties.theme === "dark" || properties.theme === "light") {
    output.theme = properties.theme;
  }
  if (properties.action && (actionAllowlist as readonly string[]).includes(properties.action)) {
    output.action = properties.action;
  }
  if (properties.role && (roleAllowlist as readonly string[]).includes(properties.role)) {
    output.role = properties.role;
  }
  if (properties.provider && (providerAllowlist as readonly string[]).includes(properties.provider)) {
    output.provider = properties.provider;
  }
  if (properties.code && (codeAllowlist as readonly string[]).includes(properties.code)) {
    output.code = properties.code;
  }
  return output;
}

const developmentAdapter: AnalyticsAdapter = {
  send(event) {
    console.info("[RehabSense event]", event.name, event.properties);
  },
};

export const productionApiAdapter: AnalyticsAdapter = {
  async send(event) {
    await fetch("/api/events", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(event),
      keepalive: true,
      credentials: "same-origin",
    });
  },
};

export function track(name: EventName, properties: SafeProperties = {}) {
  if (typeof window === "undefined") return;
  // Honour an explicit opt-out even before any collector is configured.
  const legacyDnt = (window as Window & { doNotTrack?: string }).doNotTrack;
  if (navigator.doNotTrack === "1" || legacyDnt === "1") return;
  // Nothing is sent without analytics consent from the cookie banner.
  if (!hasConsent("analytics")) return;

  const event: AnalyticsEvent = {
    name,
    at: new Date().toISOString(),
    properties: sanitize(properties),
  };

  if (process.env.NODE_ENV === "development") {
    void developmentAdapter.send(event);
  } else if (process.env.NEXT_PUBLIC_ANALYTICS_ENABLED === "true") {
    Promise.resolve(productionApiAdapter.send(event)).catch(() => {
      // Analytics failure must never interrupt the product experience.
    });
  }
}

/** Narrows an arbitrary pathname to an allowlisted route, or undefined. */
export function safeRoute(pathname: string): SafeProperties["route"] {
  return (routeAllowlist as readonly string[]).includes(pathname)
    ? (pathname as SafeProperties["route"])
    : undefined;
}
