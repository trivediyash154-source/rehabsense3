"use client";

import { useEffect, useId, useRef, useState } from "react";
import Link from "next/link";
import { Cookie } from "lucide-react";
import {
  CONSENT_OPEN_EVENT,
  analyticsAvailable,
  readConsent,
  saveConsent,
} from "@/lib/consent";

/**
 * Cookie and storage consent banner.
 *
 * Shown until the visitor decides, and reopened from "Cookie settings" (footer,
 * cookie policy page). "Accept all" and "Reject non-essential" are equally
 * prominent; nothing optional is pre-ticked; strictly necessary storage (the
 * sign-in session) is listed but cannot be switched off, because the site
 * cannot sign anyone in without it. Only categories that exist are offered.
 */
export function CookieConsent() {
  const [open, setOpen] = useState(false);
  const [customizing, setCustomizing] = useState(false);
  const [decided, setDecided] = useState(false);
  const [preferences, setPreferences] = useState(false);
  const [analytics, setAnalytics] = useState(false);
  const titleId = useId();
  const textId = useId();
  const heading = useRef<HTMLHeadingElement>(null);

  useEffect(() => {
    const existing = readConsent();
    setDecided(Boolean(existing));
    if (!existing) setOpen(true);

    const reopen = () => {
      const current = readConsent();
      setPreferences(current?.preferences ?? false);
      setAnalytics(current?.analytics ?? false);
      setDecided(Boolean(current));
      setCustomizing(true);
      setOpen(true);
      requestAnimationFrame(() => heading.current?.focus());
    };
    window.addEventListener(CONSENT_OPEN_EVENT, reopen);
    return () => window.removeEventListener(CONSENT_OPEN_EVENT, reopen);
  }, []);

  useEffect(() => {
    if (!open || !decided) return;
    // A visitor who has already chosen can dismiss the reopened panel.
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, decided]);

  if (!open) return null;

  const decide = (choice: { preferences: boolean; analytics: boolean }) => {
    saveConsent(choice);
    setDecided(true);
    setCustomizing(false);
    setOpen(false);
  };

  return (
    <section
      className="consent"
      role="dialog"
      aria-modal="false"
      aria-labelledby={titleId}
      aria-describedby={textId}
    >
      <div className="consent-head">
        <Cookie size={18} aria-hidden="true" />
        <h2 id={titleId} ref={heading} tabIndex={-1}>
          Cookies on RehabSense
        </h2>
      </div>
      <p id={textId}>
        We use cookies that are strictly necessary to keep you signed in. With your permission we
        also remember display preferences on this device
        {analyticsAvailable ? " and collect anonymous product events" : ""}. No advertising or
        third-party tracking cookies are used.{" "}
        <Link href="/cookies">Cookie policy</Link>
      </p>

      {customizing && (
        <fieldset className="consent-options">
          <legend className="sr-only">Cookie categories</legend>
          <label className="consent-option">
            <input type="checkbox" checked disabled />
            <span>
              <strong>
                Strictly necessary <em>Always on</em>
              </strong>
              <small>Sign-in session, this choice, keeping an active recording attached.</small>
            </span>
          </label>
          <label className="consent-option">
            <input
              type="checkbox"
              checked={preferences}
              onChange={(event) => setPreferences(event.target.checked)}
            />
            <span>
              <strong>Preferences</strong>
              <small>Theme, 3D or lite visuals, display settings, workspace view.</small>
            </span>
          </label>
          <label className="consent-option">
            <input
              type="checkbox"
              checked={analyticsAvailable && analytics}
              disabled={!analyticsAvailable}
              onChange={(event) => setAnalytics(event.target.checked)}
            />
            <span>
              <strong>Analytics</strong>
              <small>
                {analyticsAvailable
                  ? "Allowlisted product events. Never form contents, health data or identifiers."
                  : "Not collected on this deployment."}
              </small>
            </span>
          </label>
        </fieldset>
      )}

      <div className="consent-actions">
        {customizing ? (
          <button
            type="button"
            className="button button-outline button-small"
            onClick={() => decide({ preferences, analytics })}
          >
            Save choices
          </button>
        ) : (
          <button
            type="button"
            className="button button-outline button-small"
            onClick={() => setCustomizing(true)}
          >
            Customize
          </button>
        )}
        <button
          type="button"
          className="button button-small"
          onClick={() => decide({ preferences: false, analytics: false })}
        >
          Reject non-essential
        </button>
        <button
          type="button"
          className="button button-small"
          onClick={() => decide({ preferences: true, analytics: true })}
        >
          Accept all
        </button>
      </div>
    </section>
  );
}

/** A link-styled button that reopens the cookie settings. */
export function CookieSettingsButton({ className = "text-link" }: { className?: string }) {
  return (
    <button
      type="button"
      className={className}
      onClick={() => window.dispatchEvent(new Event(CONSENT_OPEN_EVENT))}
    >
      Cookie settings
    </button>
  );
}
