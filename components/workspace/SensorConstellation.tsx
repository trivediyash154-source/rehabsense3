"use client";

import { useState } from "react";
import { constellation, type Session } from "@/lib/demo-data";

/**
 * SENSOR CONSTELLATION
 *
 * The whole signal chain as one connected object: two limb nodes, their
 * streams, fusion and analytics, then this interface. Particles travel the
 * links continuously, and a degraded stream visibly starves.
 *
 * Selecting a node highlights its path end to end, which is the point — the
 * system is physically connected, not a set of boxes.
 */
export function SensorConstellation({ session }: { session: Session }) {
  const nodes = constellation(session);
  const [selected, setSelected] = useState<string | null>(null);

  const stageX = [70, 210, 360, 500];
  const position = (node: (typeof nodes)[number]) => {
    const x = stageX[node.stage];
    if (node.stage >= 2) return [x, node.id === "fusion" ? 96 : 164] as const;
    return [x, node.limb === "LEFT" ? 78 : 182] as const;
  };

  const links: [string, string][] = [
    ["l-node", "l-stream"],
    ["r-node", "r-stream"],
    ["l-stream", "fusion"],
    ["r-stream", "fusion"],
    ["fusion", "analytics"],
    ["analytics", "workspace"],
  ];

  const byId = Object.fromEntries(nodes.map((n) => [n.id, n]));
  const isLit = (id: string) => {
    if (!selected) return true;
    if (selected === id) return true;
    // Light the whole upstream/downstream path of the selected node.
    const chain = new Set<string>([selected]);
    let grew = true;
    while (grew) {
      grew = false;
      for (const [a, b] of links) {
        if (chain.has(a) && !chain.has(b)) { chain.add(b); grew = true; }
        if (chain.has(b) && !chain.has(a)) { chain.add(a); grew = true; }
      }
    }
    return chain.has(id);
  };

  return (
    <section className="constellation" aria-labelledby="cn-title">
      <header className="cn-head">
        <div>
          <span className="eyebrow">SENSOR CONSTELLATION</span>
          <h3 id="cn-title">Sensor to insight, as one connected system.</h3>
        </div>
        {selected && (
          <button type="button" className="text-link" onClick={() => setSelected(null)}>
            Clear selection
          </button>
        )}
      </header>

      <div className="cn-stage">
        <svg viewBox="0 0 570 250" role="img" aria-label="Signal path from two limb sensor nodes through streaming, fusion and analytics to this workspace.">
          <g className="cn-links">
            {links.map(([a, b]) => {
              const [x1, y1] = position(byId[a]);
              const [x2, y2] = position(byId[b]);
              const degraded = byId[a].status === "degraded" || byId[b].status === "degraded";
              const lit = isLit(a) && isLit(b);
              const d = `M${x1} ${y1} C${(x1 + x2) / 2} ${y1}, ${(x1 + x2) / 2} ${y2}, ${x2} ${y2}`;
              return (
                <g key={`${a}-${b}`} className={`cn-link ${degraded ? "is-degraded" : ""} ${lit ? "" : "is-dim"}`}>
                  <path d={d} className="cn-wire" />
                  <circle r="3.4" className="cn-particle">
                    <animateMotion dur={degraded ? "5.2s" : "2.6s"} repeatCount="indefinite" path={d} />
                  </circle>
                  {!degraded && (
                    <circle r="2.4" className="cn-particle cn-particle-b">
                      <animateMotion dur="2.6s" begin="-1.3s" repeatCount="indefinite" path={d} />
                    </circle>
                  )}
                </g>
              );
            })}
          </g>

          {nodes.map((node) => {
            const [x, y] = position(node);
            const lit = isLit(node.id);
            return (
              <g
                key={node.id}
                className={`cn-node status-${node.status} ${selected === node.id ? "is-selected" : ""} ${lit ? "" : "is-dim"}`}
                transform={`translate(${x} ${y})`}
                onClick={() => setSelected(selected === node.id ? null : node.id)}
                role="button"
                tabIndex={0}
                aria-pressed={selected === node.id}
                aria-label={`${node.label}, ${node.sub}, ${node.status}`}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    setSelected(selected === node.id ? null : node.id);
                  }
                }}
              >
                <circle r="26" className="cn-halo" />
                <circle r="13" className="cn-core" />
                <circle r="4.5" className="cn-pip" />
                <text y="-34" className="cn-name">{node.label}</text>
                <text y="42" className="cn-sub">{node.sub}</text>
              </g>
            );
          })}

          <g className="cn-stages">
            {["NODE", "STREAM", "ANALYTICS", "WORKSPACE"].map((label, i) => (
              <text key={label} x={stageX[i]} y="238" className="cn-stage-label">{label}</text>
            ))}
          </g>
        </svg>
      </div>

      <div className="cn-legend">
        <span><i className="dot-active" />Active</span>
        <span><i className="dot-degraded" />Degraded stream</span>
        <span className="mono">
          {session.coverage < 70
            ? `COVERAGE ${session.coverage}% · ONE LIMB INTERRUPTED`
            : `COVERAGE ${session.coverage}% · BOTH LIMBS REPORTING`}
        </span>
      </div>
    </section>
  );
}
