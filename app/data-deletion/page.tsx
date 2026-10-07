import type { Metadata } from "next";
import Link from "next/link";
import { Header, Footer } from "@/components/navigation/Header";

export const metadata: Metadata = {
  title: "Delete your data",
  description:
    "How to delete your RehabSense account and the data it holds, including data received through Google or Facebook sign-in.",
};

/**
 * The data deletion instructions URL given to Facebook (and linked from the
 * privacy notice). Each step is a feature that exists: Settings -> Sign-in
 * methods (DELETE /api/auth/identities/{provider}) and Settings -> Delete
 * account (DELETE /api/me).
 */
export default function DataDeletionPage() {
  return (
    <>
      <Header />
      <main id="main" className="container legal-page">
        <span className="eyebrow">PRIVACY</span>
        <h1>Delete your RehabSense data</h1>
        <p>
          You can delete your data yourself, at any time, without contacting anyone. Deletion takes
          effect immediately.
        </p>

        <h2>Delete your whole account</h2>
        <ol className="legal-steps">
          <li>
            <Link href="/login">Sign in</Link> with the method you normally use: email and password,
            Google or Facebook.
          </li>
          <li>Open <strong>Settings</strong> in the workspace.</li>
          <li>
            Under <strong>Delete account</strong>, choose <strong>Delete account…</strong>, type
            DELETE (and your password, if the account has one), then confirm.
          </li>
        </ol>
        <p>
          This permanently deletes your account, your name, email address and phone number, every
          connected Google or Facebook sign-in (including the identifier and email received from
          them), your preferences and notifications, and ends every session on every device. A
          patient record that a clinician created stays in that clinician&apos;s records, no longer
          linked to your account.
        </p>

        <h2>Remove only the Google or Facebook connection</h2>
        <ol className="legal-steps">
          <li>Sign in and open <strong>Settings</strong>.</li>
          <li>
            Under <strong>Sign-in methods</strong>, choose <strong>Disconnect</strong> next to Google
            or Facebook. The stored identifier and email address from that provider are deleted
            immediately. (If it is your only way to sign in, delete the account instead.)
          </li>
        </ol>

        <h2>Revoke access on Facebook or Google as well</h2>
        <p>
          RehabSense keeps no Facebook or Google tokens, but you can also remove it from your
          provider account: on Facebook, Settings &amp; privacy → Settings → Apps and websites →
          RehabSense → Remove; on Google, myaccount.google.com → Security → Your connections to
          third-party apps &amp; services → RehabSense → Delete all connections.
        </p>

        <p>
          See the <Link href="/privacy">privacy notice</Link> for everything RehabSense stores.
        </p>
      </main>
      <Footer />
    </>
  );
}
