import type { Metadata } from "next";
import Link from "next/link";
import { Header, Footer } from "@/components/navigation/Header";

export const metadata: Metadata = {
  title: "Privacy notice",
  description:
    "What the RehabSense research prototype stores about you, including Google and Facebook sign-in, where it is kept, and how to delete it.",
};

/**
 * Written from the code, not from aspiration: every item below corresponds to
 * a column the backend stores or a request it makes. If the code changes,
 * this page changes with it.
 */
export default function PrivacyPage() {
  return (
    <>
      <Header />
      <main id="main" className="container legal-page">
        <span className="eyebrow">PRIVACY</span>
        <h1>Privacy notice</h1>
        <p>
          RehabSense is a student research prototype for wearable lower-limb movement sensing. It is
          not a medical device and not a clinical service. This notice describes what the prototype
          deployed at this address stores and why. Do not enter sensitive health information you are
          not comfortable sharing with a research prototype.
        </p>

        <h2>Your account</h2>
        <p>
          When you create an account, RehabSense stores your name, email address, the role you
          chose (patient, physiotherapist or researcher), an optional phone number (never verified,
          never messaged), your time zone and display preferences. If you sign up with email, your
          password is stored only as an Argon2id hash. It also keeps the time of your last sign-in
          and a count of recent failed sign-ins, to protect the account from password guessing.
        </p>

        <h2>Signing in with Google or Facebook</h2>
        <p>
          You sign in on Google&apos;s or Facebook&apos;s own page; RehabSense never sees your
          Google or Facebook password. From Google, RehabSense receives your Google account
          identifier, name, email address and whether Google has verified that address (scopes:
          openid, email, profile). From Facebook, it receives your app-specific Facebook user
          identifier, name and email address (permissions: public_profile, email). It stores the
          identifier, the email address and when you last used it. It does not store Google or
          Facebook access tokens, does not read your contacts, friends, photos or posts, and never
          posts anything on your behalf.
        </p>
        <p>
          A Google or Facebook account is only ever connected to an existing RehabSense account
          while you are signed in to that account. RehabSense never joins accounts because two email
          addresses match.
        </p>

        <h2>Movement and session data</h2>
        <p>
          Sessions recorded with RehabSense hardware or its simulator store the sensor stream,
          calibration results, computed movement indicators and activity-model outputs, linked to
          the patient record they were recorded for. Raw sensor samples are kept for 30 days unless
          they are retained for research under a consent recorded in the workspace. Every figure is
          an estimated decision-support indicator, not a diagnosis.
        </p>

        <h2>Cookies and logs</h2>
        <p>
          Sign-in uses HttpOnly session cookies that page scripts cannot read; the{" "}
          <Link href="/cookies">cookie policy</Link> lists every cookie and storage entry. The server
          keeps an audit trail of security-relevant actions (sign-ins, sign-in failures, connected
          providers) with identifiers and outcomes only, and operational logs that never contain
          passwords, sign-in codes or tokens.
        </p>

        <h2>Where it is stored</h2>
        <p>
          The website and API run on Vercel in the United States. Data is stored in a Neon
          PostgreSQL database hosted on Amazon Web Services in the United States (Ohio). Nothing is
          sold or shared with advertisers, and no third-party tracking is used.
        </p>

        <h2>Deleting your data</h2>
        <p>
          You can disconnect Google or Facebook, or permanently delete your whole account, at any
          time from <strong>Settings</strong> in the workspace. Step-by-step instructions are on the{" "}
          <Link href="/data-deletion">data deletion page</Link>.
        </p>

        <h2>Before real patient data</h2>
        <p>
          This prototype has not been through a clinical, legal or data-protection review. A named
          data controller, retention schedule, lawful basis for processing health data and a
          documented user-rights process must be in place before it is used with real patients.
        </p>
      </main>
      <Footer />
    </>
  );
}
