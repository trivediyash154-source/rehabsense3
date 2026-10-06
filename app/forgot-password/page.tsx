import { Suspense } from "react";
import type { Metadata } from "next";
import { AuthScreen } from "@/components/auth/AuthScreen";

export const metadata: Metadata = {
  title: "Password reset unavailable",
  description: "Password reset is not available in this RehabSense research prototype: no email provider is connected.",
  robots: { index: false, follow: false },
};

export default function Page() {
  return (
    <Suspense fallback={null}>
      <AuthScreen mode="forgot-password" />
    </Suspense>
  );
}
