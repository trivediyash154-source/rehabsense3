"use client";

import { useEffect, useRef, type ReactNode } from "react";
import { motion } from "framer-motion";
import { X, ArrowUpRight } from "lucide-react";

export function Reveal({
  children,
  className = "",
  delay = 0,
}: {
  children: ReactNode;
  className?: string;
  delay?: number;
}) {
  return (
    <motion.div
      className={className}
      initial={{ opacity: 0, y: 22 }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, amount: 0.12 }}
      transition={{ duration: 0.8, delay, ease: [0.22, 1, 0.36, 1] }}
    >
      {children}
    </motion.div>
  );
}

export function Eyebrow({ children, index }: { children: ReactNode; index?: string }) {
  return (
    <div className="eyebrow">
      {index && <span>{index} /</span>}
      {children}
    </div>
  );
}

export function DemoBadge({ variant = "data" }: { variant?: "data" | "interface" | "concept" }) {
  const label =
    variant === "interface"
      ? "Illustrative prototype interface"
      : variant === "concept"
        ? "Prototype visualization"
        : "Illustrative interface data";
  return (
    <span className="demo-badge">
      <span aria-hidden="true" />
      {label}
    </span>
  );
}

export function SectionHeading({
  index,
  label,
  title,
  copy,
  align = "start",
}: {
  index: string;
  label: string;
  title: ReactNode;
  copy?: string;
  align?: "start" | "center";
}) {
  return (
    <Reveal className={`section-heading ${align === "center" ? "is-centered" : ""}`}>
      <Eyebrow index={index}>{label}</Eyebrow>
      <h2>{title}</h2>
      {copy && <p className="lede">{copy}</p>}
    </Reveal>
  );
}

export function Modal({
  open,
  onClose,
  title,
  children,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  children: ReactNode;
}) {
  const ref = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    if (!open && dialog.open) dialog.close();
  }, [open]);

  return (
    <dialog
      ref={ref}
      className="modal"
      aria-labelledby="modal-title"
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
      onClose={onClose}
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div className="modal-body">
        <div className="modal-heading">
          <h2 id="modal-title">{title}</h2>
          <button
            type="button"
            className="icon-button"
            aria-label="Close dialog"
            onClick={onClose}
          >
            <X size={20} />
          </button>
        </div>
        {children}
      </div>
    </dialog>
  );
}

export function TextLink({ href, children }: { href: string; children: ReactNode }) {
  return (
    <a className="text-link" href={href}>
      {children}
      <ArrowUpRight size={16} />
    </a>
  );
}

/**
 * A soft light that follows a fine pointer. Skipped entirely for touch input
 * and for users who prefer reduced motion.
 */
export function CursorField() {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!matchMedia("(pointer:fine) and (prefers-reduced-motion:no-preference)").matches) {
      return;
    }
    let frame = 0;
    const move = (event: PointerEvent) => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        const node = ref.current;
        if (!node) return;
        node.style.opacity = "1";
        node.style.transform = `translate3d(${event.clientX - 190}px,${event.clientY - 190}px,0)`;
      });
    };
    window.addEventListener("pointermove", move, { passive: true });
    return () => {
      window.removeEventListener("pointermove", move);
      cancelAnimationFrame(frame);
    };
  }, []);

  return <div className="cursor-field" ref={ref} aria-hidden="true" />;
}
