import type { Metadata } from "next";
import { Header, Footer } from "@/components/navigation/Header";
import { CookieSettingsButton } from "@/components/ui/CookieConsent";

export const metadata: Metadata = {
  title: "Cookie policy",
  description:
    "The cookies and on-device storage RehabSense uses, why, for how long, and how to change your choice.",
};

/**
 * Every cookie and storage key the site uses, listed from the code that sets
 * it (backend/app/core/cookies.py, lib/consent.ts and the preference call
 * sites). Nothing here is aspirational: if a row is added to the code, it
 * belongs here too.
 */
const rows: [name: string, kind: string, purpose: string, duration: string, category: string][] = [
  ["rs_session", "Cookie, HttpOnly, Secure, SameSite=Lax (set by the RehabSense API)",
    "Keeps you signed in. Page scripts cannot read it.", "12 hours", "Strictly necessary"],
  ["rs_refresh", "Cookie, HttpOnly, Secure, SameSite=Lax, sent only to /api/auth/refresh",
    "Renews your session without asking for your password again.", "14 days", "Strictly necessary"],
  ["rs_consent", "Cookie, SameSite=Lax",
    "Remembers your cookie choices. Holds the choices and a date, no identifier.", "6 months", "Strictly necessary"],
  ["rehabsense-live-session, rehabsense-hw-session", "Browser storage (localStorage)",
    "Re-attaches an active recording if the page reloads mid-session.", "Until the session ends", "Strictly necessary"],
  ["error reload guard", "Browser storage (sessionStorage)",
    "Stops an error-recovery reload from repeating.", "This tab only", "Strictly necessary"],
  ["rehabsense-theme, rehabsense-lite", "Browser storage (localStorage)",
    "Light or dark theme; 3D or lite visuals.", "Until you clear it or reject preferences", "Preferences"],
  ["rehabsense-density, rehabsense-datefmt, rehabsense-units", "Browser storage (localStorage)",
    "Workspace display settings.", "Until you clear it or reject preferences", "Preferences"],
  ["rehabsense-role, rehabsense-selected-patient, rehabsense-illustrative-mode", "Browser storage (localStorage)",
    "Workspace view, the record you last opened, and whether you chose illustrative data.",
    "Until you clear it or reject preferences", "Preferences"],
  ["Product events", "Network requests, no cookie",
    "Allowlisted interaction events (e.g. a page was viewed). Never form contents, health data or identifiers. Collected only if this deployment enables it and you allow analytics.",
    "Not stored in your browser", "Analytics"],
];

export default function CookiesPage() {
  return (
    <>
      <Header />
      <main id="main" className="container legal-page">
        <span className="eyebrow">PRIVACY</span>
        <h1>Cookies and on-device storage</h1>
        <p>
          RehabSense uses a small number of cookies and browser storage entries. Strictly necessary
          ones keep you signed in and cannot be switched off. Preferences and analytics are used
          only if you allow them, and rejecting preferences deletes the ones already stored on this
          device. RehabSense sets no advertising, social media or third-party tracking cookies.
        </p>
        <p>
          <CookieSettingsButton className="button button-small" />
        </p>

        <div className="legal-table-wrap">
          <table className="legal-table">
            <caption className="sr-only">Cookies and storage used by RehabSense</caption>
            <thead>
              <tr>
                <th scope="col">Name</th>
                <th scope="col">Type</th>
                <th scope="col">Purpose</th>
                <th scope="col">Duration</th>
                <th scope="col">Category</th>
              </tr>
            </thead>
            <tbody>
              {rows.map(([name, kind, purpose, duration, category]) => (
                <tr key={name}>
                  <th scope="row" className="mono">{name}</th>
                  <td>{kind}</td>
                  <td>{purpose}</td>
                  <td>{duration}</td>
                  <td>{category}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <p className="fine-print">
          RehabSense is a research prototype, not a medical device. Questions about data handling:
          use the contact page.
        </p>
      </main>
      <Footer />
    </>
  );
}
