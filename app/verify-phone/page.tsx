import { Suspense } from "react";
import type { Metadata } from "next";
import { AuthScreen } from "@/components/auth/AuthScreen";

export const metadata: Metadata = {
  title: "Phone verification unavailable",
  description: "Phone verification is not available in this RehabSense research prototype: no SMS provider is connected.",
  robots: { index: false, follow: false },
};

export default function Page() {
  return (
    <Suspense fallback={null}>
      <AuthScreen mode="verify-phone" />
    </Suspense>
  );
}
