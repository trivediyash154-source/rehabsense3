"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { Menu, X, ArrowUpRight } from "lucide-react";
import { Logo } from "@/components/brand/Logo";
import { ThemeToggle } from "@/components/ui/Providers";
import { LiteToggle } from "@/components/three/SceneContext";

const links: [string, string, string][] = [
  ["Product", "/#product", "product"],
  ["The gap", "/#gap", "gap"],
  ["How it works", "/#how-it-works", "how-it-works"],
  ["Features", "/#features", "features"],
  ["Recovery score", "/#recovery-score", "recovery-score"],
  ["Research", "/#research", "research"],
];

export function Header() {
  const [scrolled, setScrolled] = useState(false);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState("");
  const dialog = useRef<HTMLDialogElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    const update = () => setScrolled(window.scrollY > 24);
    update();
    window.addEventListener("scroll", update, { passive: true });

    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) if (entry.isIntersecting) setActive(entry.target.id);
      },
      { rootMargin: "-15% 0px -60% 0px" },
    );
    document.querySelectorAll("section[id]").forEach((section) => observer.observe(section));

    return () => {
      window.removeEventListener("scroll", update);
      observer.disconnect();
    };
  }, []);

  // <dialog> gives us focus trapping, Escape handling and inert background.
  useEffect(() => {
    const node = dialog.current;
    if (!node) return;
    if (open) {
      if (!node.open) node.showModal();
      const previous = document.body.style.overflow;
      document.body.style.overflow = "hidden";
      return () => {
        document.body.style.overflow = previous;
      };
    }
    if (node.open) node.close();
  }, [open]);

  const close = () => {
    setOpen(false);
    trigger.current?.focus();
  };

  return (
    <>
      <header className={`site-header ${scrolled ? "is-scrolled" : ""}`}>
        <div className="nav-shell">
          <Logo />
          <nav className="desktop-nav" aria-label="Main navigation">
            {links.map(([label, href, id]) => (
              <Link key={href} href={href} aria-current={id === active ? "location" : undefined}>
                {label}
              </Link>
            ))}
          </nav>
          <div className="nav-actions">
            <ThemeToggle />
            <Link className="sign-in" href="/login">
              Sign in
            </Link>
            <Link className="button button-small nav-cta" href="/signup">
              Get started
              <ArrowUpRight size={15} />
            </Link>
            <button
              ref={trigger}
              type="button"
              className="icon-button mobile-menu"
              onClick={() => setOpen(true)}
              aria-label="Open navigation"
              aria-expanded={open}
            >
              <Menu size={22} />
            </button>
          </div>
        </div>
      </header>

      <dialog
        ref={dialog}
        className="nav-drawer"
        aria-label="Navigation"
        onCancel={(event) => {
          event.preventDefault();
          close();
        }}
        onClose={() => setOpen(false)}
      >
        <div className="drawer-top">
          <Logo />
          <button type="button" className="icon-button" onClick={close} aria-label="Close navigation">
            <X size={22} />
          </button>
        </div>
        <nav aria-label="Mobile navigation">
          {[...links, ["Contact", "/contact", "contact"] as [string, string, string]].map(
            ([label, href], i) => (
              <Link href={href} key={href} onClick={close}>
                <span className="mono">{String(i + 1).padStart(2, "0")}</span>
                {label}
                <ArrowUpRight size={18} />
              </Link>
            ),
          )}
        </nav>
        <div className="drawer-bottom">
          <Link href="/login" className="button button-outline" onClick={close}>
            Sign in
          </Link>
          <Link href="/signup" className="button" onClick={close}>
            Get started
          </Link>
        </div>
        <div className="drawer-foot">
          <ThemeToggle systemOption />
          <p className="fine-print">
            Make recovery visible.
            <br />
            Research prototype — not a diagnostic device.
          </p>
        </div>
      </dialog>
    </>
  );
}

export function Footer() {
  return (
    <footer className="site-footer">
      <div className="container footer-grid">
        <div className="footer-brand">
          <Logo />
          <p>
            One body. Two legs.
            <br />
            A clearer recovery story.
          </p>
          <span className="mono">VISHWAKARMA INSTITUTE OF TECHNOLOGY</span>
        </div>
        <nav className="footer-links" aria-label="Footer">
          <span className="mono">EXPLORE</span>
          <Link href="/#how-it-works">How it works</Link>
          <Link href="/#features">Features</Link>
          <Link href="/dashboard">Demo workspace</Link>
        </nav>
        <nav className="footer-links" aria-label="Footer secondary">
          <span className="mono">RESPONSIBILITY</span>
          <Link href="/#responsible">Responsible use &amp; privacy</Link>
          <Link href="/#research">Technical foundation</Link>
          <Link href="/contact">Contact the team</Link>
        </nav>
        <div className="footer-meta">
          <div className="footer-controls">
            <ThemeToggle systemOption />
            <LiteToggle />
          </div>
          <span>© {new Date().getFullYear()} RehabSense</span>
          <span>Research prototype. Estimated indicators, not clinical measurements.</span>
        </div>
      </div>
    </footer>
  );
}
