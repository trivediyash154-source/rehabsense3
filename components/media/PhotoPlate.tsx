"use client";

import { useState } from "react";

/**
 * The photographic layer's treatment shell.
 *
 * `public/` holds no licensed photography, so this renders a designed plate —
 * a procedural depth field in the product's own visual language — until an
 * approved asset is supplied. Passing `src` swaps the artwork in with no
 * layout change; the overlay, edge light, grain and caption are identical
 * either way, so commissioning photos later cannot destabilise the design.
 *
 * Art direction for the fifteen planned images: docs/IMAGE_PROMPTS.md
 */
export function PhotoPlate({
  src,
  alt,
  caption,
  ratio = "16 / 9",
  tone = "cool",
  className = "",
}: {
  /** Omit until an approved, licensed asset exists. */
  src?: string;
  alt: string;
  caption: string;
  ratio?: string;
  tone?: "cool" | "warm";
  className?: string;
}) {
  const [failed, setFailed] = useState(false);
  const showImage = Boolean(src) && !failed;

  return (
    <figure className={`photo-plate tone-${tone} ${className}`} style={{ aspectRatio: ratio }}>
      <div className="plate-media">
        {showImage ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={src} alt={alt} loading="lazy" decoding="async" onError={() => setFailed(true)} />
        ) : (
          <PendingPlate />
        )}
      </div>

      <div className="plate-overlay" aria-hidden="true" />
      <div className="plate-edge" aria-hidden="true" />
      <div className="plate-sweep" aria-hidden="true" />
      <div className="plate-grain" aria-hidden="true" />

      <figcaption>
        <span className="mono">{caption}</span>
      </figcaption>
    </figure>
  );
}

/**
 * The awaiting-artwork state. Not a grey box: a depth field built from the
 * same movement language as the rest of the product, so a plate without a
 * photograph still reads as designed.
 */
function PendingPlate() {
  return (
    <div className="plate-pending">
      <svg viewBox="0 0 480 270" preserveAspectRatio="xMidYMid slice" aria-hidden="true">
        <defs>
          <linearGradient id="pp-a" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%" stopColor="var(--cyan)" stopOpacity="0.16" />
            <stop offset="100%" stopColor="var(--violet)" stopOpacity="0.05" />
          </linearGradient>
        </defs>
        <rect width="480" height="270" fill="url(#pp-a)" />
        {[0, 1, 2, 3, 4, 5].map((i) => (
          <path
            key={i}
            className="pp-strand"
            d={`M-20 ${40 + i * 40} C 120 ${10 + i * 44}, 300 ${120 + i * 26}, 500 ${60 + i * 38}`}
            style={{ animationDelay: `${i * 0.5}s` }}
          />
        ))}
        <circle className="pp-node" cx="168" cy="120" r="5" />
        <circle className="pp-node" cx="312" cy="164" r="5" style={{ animationDelay: "1.1s" }} />
        <line className="pp-link" x1="168" y1="120" x2="312" y2="164" />
      </svg>
      <span className="mono plate-pending-label">AWAITING APPROVED PHOTOGRAPHY</span>
    </div>
  );
}
