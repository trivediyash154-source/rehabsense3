import type { Metadata, Viewport } from "next";
import { Inter, IBM_Plex_Mono } from "next/font/google";
import { Providers } from "@/components/ui/Providers";
import { AuthProvider } from "@/components/auth/AuthProvider";
import { getServerUser } from "@/lib/server/session";
import { SceneLayer } from "@/components/three/SceneLayer";
import { SceneStatusProvider } from "@/components/three/SceneContext";
import { CursorField } from "@/components/ui/Primitives";
import { themeBootScript } from "@/lib/theme";
import { CookieConsent } from "@/components/ui/CookieConsent";
import "./globals.css";
import { siteUrl as siteUrl_ } from "@/lib/config.server";

// Self-hosted at build time: no runtime request to a third-party font CDN.
const sans = Inter({
  subsets: ["latin"],
  display: "swap",
  variable: "--font-sans",
  axes: ["opsz"],
});

const mono = IBM_Plex_Mono({
  subsets: ["latin"],
  weight: ["400", "500"],
  display: "swap",
  variable: "--font-mono",
});

const siteUrl = siteUrl_();

export const metadata: Metadata = {
  metadataBase: new URL(siteUrl),
  title: {
    default: "RehabSense — Make recovery visible.",
    template: "%s | RehabSense",
  },
  description:
    "A research prototype exploring wearable lower-limb movement sensing, bilateral comparison and explainable rehabilitation indicators. Not a medical device.",
  applicationName: "RehabSense",
  keywords: [
    "rehabilitation",
    "wearable sensing",
    "gait analysis",
    "ACL recovery",
    "research prototype",
  ],
  openGraph: {
    title: "RehabSense — Make recovery visible.",
    description:
      "Wearable lower-limb movement sensing, bilateral comparison and explainable recovery indicators. A research prototype.",
    type: "website",
    siteName: "RehabSense",
  },
  robots: { index: true, follow: true },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: [
    { media: "(prefers-color-scheme: dark)", color: "#04070f" },
    { media: "(prefers-color-scheme: light)", color: "#f6f9fc" },
  ],
};

export default async function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  // Resolved server-side so the first paint already knows who is signed in.
  const { user, resolved } = await getServerUser();

  return (
    <html lang="en" suppressHydrationWarning className={`${sans.variable} ${mono.variable}`}>
      <head>
        {/* Applies the stored theme before first paint, avoiding a flash. */}
        <script dangerouslySetInnerHTML={{ __html: themeBootScript }} />
      </head>
      <body>
        <a className="skip-link" href="#main">
          Skip to content
        </a>
        <Providers>
          <AuthProvider initialUser={user} serverResolved={resolved}>
            <SceneStatusProvider>
              <SceneLayer />
              <CursorField />
              <div className="page-layer">{children}</div>
              <CookieConsent />
            </SceneStatusProvider>
          </AuthProvider>
        </Providers>
      </body>
    </html>
  );
}
