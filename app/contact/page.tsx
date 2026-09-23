import type { Metadata } from "next";
import { Header, Footer } from "@/components/navigation/Header";
import { ContactSection } from "@/components/sections/Landing";

export const metadata: Metadata = {
  title: "Start a conversation",
  description:
    "Contact the RehabSense team about demonstrations, research collaboration or clinical discussion.",
};

export default function ContactPage() {
  return (
    <>
      <Header />
      <main id="main">
        <ContactSection standalone />
      </main>
      <Footer />
    </>
  );
}
