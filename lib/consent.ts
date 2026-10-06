/**
 * Cookie and on-device storage consent.
 *
 * The categories are the ones this site actually uses; nothing is listed
 * that does not exist (there are no advertising or third-party cookies):
 *
 *   necessary    always on: the sign-in cookies the API sets (rs_session,
 *                rs_refresh, both HttpOnly), this consent record, the keys
 *                that keep an active recording attached across a reload, and
 *                a one-shot error-reload guard.
 *   preferences  remembered display choices: theme, 3D/lite visuals,
 *                density, date format, units, workspace view, the selected
 *                record and illustrative mode.
 *   analytics    allowlisted product events, and only on a deployment that
 *                enables collection at all (NEXT_PUBLIC_ANALYTICS_ENABLED).
 *
 * The record is a first-party cookie, so the choice holds across tabs and
 * reloads. It stores the choices and a timestamp, no identifier.
 */

export type ConsentCategory = "preferences" | "analytics";

export type ConsentRecord = {
  v: 1;
  preferences: boolean;
  analytics: boolean;
  at: string;
};

export const CONSENT_COOKIE = "rs_consent";
/** Six months, after which the visitor is asked again. */
const CONSENT_MAX_AGE_S = 60 * 60 * 24 * 182;

export const CONSENT_EVENT = "rehabsense:consent";
export const CONSENT_OPEN_EVENT = "rehabsense:consent-open";

/** Collection is possible on this deployment at all (inlined at build time). */
export const analyticsAvailable = process.env.NEXT_PUBLIC_ANALYTICS_ENABLED === "true";

/** localStorage keys holding preferences; cleared when preferences are declined. */
export const PREFERENCE_KEYS = [
  "rehabsense-theme",
  "rehabsense-lite",
  "rehabsense-density",
  "rehabsense-datefmt",
  "rehabsense-units",
  "rehabsense-role",
  "rehabsense-selected-patient",
  "rehabsense-illustrative-mode",
] as const;

export type PreferenceKey = (typeof PREFERENCE_KEYS)[number];

export function readConsent(): ConsentRecord | null {
  if (typeof document === "undefined") return null;
  const raw = document.cookie
    .split("; ")
    .find((entry) => entry.startsWith(`${CONSENT_COOKIE}=`));
  if (!raw) return null;
  try {
    const parsed = JSON.parse(decodeURIComponent(raw.slice(CONSENT_COOKIE.length + 1))) as Partial<ConsentRecord>;
    if (parsed.v === 1 && typeof parsed.preferences === "boolean" && typeof parsed.analytics === "boolean") {
      return parsed as ConsentRecord;
    }
  } catch {
    // A malformed record counts as no decision; the banner asks again.
  }
  return null;
}

export function saveConsent(choice: { preferences: boolean; analytics: boolean }): ConsentRecord {
  const record: ConsentRecord = {
    v: 1,
    preferences: choice.preferences,
    // Never record agreement to something this deployment does not do.
    analytics: choice.analytics && analyticsAvailable,
    at: new Date().toISOString(),
  };
  const secure = window.location.protocol === "https:" ? "; Secure" : "";
  document.cookie =
    `${CONSENT_COOKIE}=${encodeURIComponent(JSON.stringify(record))}; Max-Age=${CONSENT_MAX_AGE_S}; ` +
    `Path=/; SameSite=Lax${secure}`;
  if (!record.preferences) {
    try {
      for (const key of PREFERENCE_KEYS) localStorage.removeItem(key);
    } catch {
      // Storage unavailable: nothing was stored in the first place.
    }
  }
  window.dispatchEvent(new CustomEvent<ConsentRecord>(CONSENT_EVENT, { detail: record }));
  return record;
}

export function hasConsent(category: ConsentCategory): boolean {
  return readConsent()?.[category] === true;
}

/**
 * Remember a preference on this device only if the visitor allowed it.
 * Without consent the choice still applies to the page in front of them; it
 * just is not written down. Removing a stored value is always allowed.
 */
export function storePreference(key: PreferenceKey, value: string | null): void {
  try {
    if (value === null) localStorage.removeItem(key);
    else if (hasConsent("preferences")) localStorage.setItem(key, value);
  } catch {
    // Storage unavailable (private mode, blocked site data).
  }
}

/** Reopen the cookie settings (footer link, cookie policy page, settings). */
export function openConsentSettings(): void {
  window.dispatchEvent(new Event(CONSENT_OPEN_EVENT));
}
