"use client";

import type { ReactNode } from "react";
import { LoaderCircle, TriangleAlert } from "lucide-react";
import type { MovementStatus, TrendWord } from "@/lib/api/movement";
import { STATUS_LABEL, TREND_ARROW } from "@/lib/movement-format";

export function Panel({
  eyebrow,
  title,
  actions,
  children,
  className = "",
  footer,
}: {
  eyebrow?: string;
  title?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
  footer?: ReactNode;
}) {
  return (
    <section className={`mv-panel ${className}`}>
      {(eyebrow || title || actions) && (
        <header className="mv-panel-head">
          <div>
            {eyebrow && <span className="eyebrow">{eyebrow}</span>}
            {title && <h3>{title}</h3>}
          </div>
          {actions && <div className="mv-panel-actions">{actions}</div>}
        </header>
      )}
      {children}
      {footer && <footer className="mv-panel-foot fine-print">{footer}</footer>}
    </section>
  );
}

export type Tone = "cyan" | "teal" | "violet" | "amber" | "coral" | "blue" | "muted";

export function Kpi({
  label,
  value,
  sub,
  tone = "cyan",
}: {
  label: string;
  value: ReactNode;
  sub?: ReactNode;
  tone?: Tone;
}) {
  return (
    <div className={`mv-kpi tone-${tone}`}>
      <span className="mono">{label}</span>
      <strong>{value}</strong>
      {sub && <small>{sub}</small>}
    </div>
  );
}

export function KpiGrid({ children }: { children: ReactNode }) {
  return <div className="mv-kpis">{children}</div>;
}

export function StatusChip({ status }: { status: MovementStatus | string | null | undefined }) {
  if (!status) return null;
  return <span className={`mv-status mv-status-${status.toLowerCase()}`}>{STATUS_LABEL[status] ?? status}</span>;
}

/** A trend in words; `lowerIsBetter` flips the colour, never the direction. */
export function TrendTag({ trend, label }: { trend: TrendWord | null | undefined; label?: string }) {
  if (!trend) return null;
  return (
    <span className={`mv-trend mv-trend-${trend}`}>
      <span aria-hidden="true">{TREND_ARROW[trend]}</span> {label ?? trend}
    </span>
  );
}

export function Loading({ what = "data" }: { what?: string }) {
  return (
    <div className="mv-state" aria-live="polite">
      <LoaderCircle className="spin" size={18} aria-hidden="true" />
      <span>Loading {what}…</span>
    </div>
  );
}

export function Failure({ error, retry }: { error: string; retry?: () => void }) {
  return (
    <div className="mv-state is-error" role="alert">
      <TriangleAlert size={18} aria-hidden="true" />
      <span>{error}</span>
      {retry && (
        <button type="button" className="button button-outline button-small" onClick={retry}>
          Try again
        </button>
      )}
    </div>
  );
}
