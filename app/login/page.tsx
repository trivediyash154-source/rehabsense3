import { Suspense } from "react";
import type { Metadata } from "next";
import { AuthScreen } from "@/components/auth/AuthScreen";

export const metadata: Metadata = {
  title: "Sign in",
  description: "Sign in to the RehabSense research prototype workspace.",
  robots: { index: false, follow: false },
};

export default function Page() {
  // AuthScreen reads the `next` query parameter to return the visitor to the
  // page they were trying to reach, which requires a Suspense boundary.
  return (
    <Suspense fallback={null}>
      <AuthScreen mode="login" />
    </Suspense>
  );
}
