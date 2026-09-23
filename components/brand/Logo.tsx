import Link from "next/link";

export function Logo({ compact = false }: { compact?: boolean }) {
  return (
    <Link className={`brand ${compact ? "brand-compact" : ""}`} href="/" aria-label="RehabSense home">
      <span className="brand-mark" aria-hidden="true">
        <svg width="30" height="32" viewBox="0 0 30 32" fill="none">
          <path d="M4 25V7h7.5c7.5 0 7.5 10.5 0 10.5H4" stroke="currentColor" strokeWidth="2.2" strokeLinecap="square" />
          <path d="m12 17.5 6.5 7.5" stroke="currentColor" strokeWidth="2.2" strokeLinecap="square" />
          <path d="M21.5 4v9m0 6v9" stroke="var(--cyan)" strokeWidth="2" strokeLinecap="round" />
          <path d="M17 10.5h9" stroke="var(--cyan)" strokeWidth="1.2" opacity=".55" />
          <circle cx="21.5" cy="16" r="2.6" fill="var(--cyan)" />
        </svg>
      </span>
      <span className="brand-word">
        rehab<span className="brand-light">sense</span>
        <span className="brand-dot">.</span>
      </span>
    </Link>
  );
}
