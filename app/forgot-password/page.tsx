import { Suspense } from "react";
import type { Metadata } from "next";
import { AuthScreen } from "@/components/auth/AuthScreen";

export const metadata: Metadata = {
  title: "Reset your password",
  description: "RehabSense research prototype. Message delivery is not configured, so no email or code is sent.",
  robots: { index: false, follow: false },
};

export default function Page() {
  return (
    <Suspense fallback={null}>
      <AuthScreen mode="forgot-password" />
    </Suspense>
  );
}
