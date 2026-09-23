"use client";

import type { ReactNode } from "react";

/**
 * One settings row: what it is on the left, the control on the right.
 *
 * The conventional shape every desktop and mobile app uses, so the page is
 * scannable and each control sits next to the sentence explaining it.
 */
export function SettingsRow({
  label,
  description,
  control,
  htmlFor,
}: {
  label: string;
  description?: ReactNode;
  control: ReactNode;
  htmlFor?: string;
}) {
  return (
    <div className="set-row">
      <div className="set-row-text">
        {htmlFor ? (
          <label htmlFor={htmlFor}>{label}</label>
        ) : (
          <span className="set-row-label">{label}</span>
        )}
        {description && <p>{description}</p>}
      </div>
      <div className="set-row-control">{control}</div>
    </div>
  );
}

export function SettingsSection({
  title,
  note,
  children,
}: {
  title: string;
  note?: string;
  children: ReactNode;
}) {
  return (
    <section className="set-section" aria-labelledby={`sec-${title.replace(/\s+/g, "-").toLowerCase()}`}>
      <header>
        <h2 id={`sec-${title.replace(/\s+/g, "-").toLowerCase()}`}>{title}</h2>
        {note && <p>{note}</p>}
      </header>
      <div className="set-rows">{children}</div>
    </section>
  );
}

/** A standard on/off switch. */
export function Toggle({
  checked,
  onChange,
  id,
  label,
  disabled,
}: {
  checked: boolean;
  onChange: (next: boolean) => void;
  id: string;
  label: string;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      id={id}
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      className={`set-toggle ${checked ? "is-on" : ""}`}
      onClick={() => onChange(!checked)}
    >
      <span className="set-knob" aria-hidden="true" />
    </button>
  );
}
