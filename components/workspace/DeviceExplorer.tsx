"use client";

import { useState, type CSSProperties } from "react";
import { RotateCcw, Layers, Minimize2 } from "lucide-react";
import { deviceComponents } from "@/lib/demo-data";

/**
 * 3D DEVICE EXPLORER
 *
 * The conceptual sensing assembly as a stack of CSS-3D planes. Rotate with
 * the sliders or by dragging; explode to separate the layers; select a part
 * to isolate it and read its role in the signal path.
 *
 * CSS 3D rather than WebGL: it costs nothing, works in Lite and reduced
 * motion, and an exploded stack of flat parts is exactly what CSS planes do
 * well. Everything here is explicitly conceptual — no manufactured hardware
 * exists to model.
 */
export function DeviceExplorer() {
  const [yaw, setYaw] = useState(-28);
  const [pitch, setPitch] = useState(58);
  const [explode, setExplode] = useState(1);
  const [selected, setSelected] = useState<string | null>("esp32");
  const [drag, setDrag] = useState(false);

  const part = deviceComponents.find((c) => c.id === selected) ?? null;

  return (
    <div className="explorer">
      <div
        className={`explorer-stage ${drag ? "is-dragging" : ""}`}
        onPointerDown={(e) => {
          setDrag(true);
          e.currentTarget.setPointerCapture(e.pointerId);
        }}
        onPointerUp={() => setDrag(false)}
        onPointerCancel={() => setDrag(false)}
        onPointerMove={(e) => {
          if (!drag) return;
          setYaw((y) => Math.max(-80, Math.min(20, y + e.movementX * 0.3)));
          setPitch((p) => Math.max(20, Math.min(80, p - e.movementY * 0.25)));
        }}
      >
        <div
          className="explorer-scene"
          style={{ "--yaw": `${yaw}deg`, "--pitch": `${pitch}deg` } as CSSProperties}
        >
          {deviceComponents.map((c, i) => {
            const on = selected === c.id;
            const dim = selected !== null && !on;
            return (
              <button
                key={c.id}
                type="button"
                className={`explorer-layer layer-${c.id} ${on ? "is-selected" : ""} ${dim ? "is-dim" : ""}`}
                style={{ "--i": i, "--explode": explode } as CSSProperties}
                onClick={() => setSelected(on ? null : c.id)}
                aria-pressed={on}
                aria-label={`${c.name} — ${c.role}`}
              >
                <span className="layer-face">
                  <span className="layer-code mono">{c.code}</span>
                  <span className="layer-name">{c.name}</span>
                </span>
              </button>
            );
          })}
          <div className="explorer-axis" aria-hidden="true" />
        </div>

        <span className="explorer-watermark mono">CONCEPTUAL ASSEMBLY · NOT MANUFACTURED HARDWARE</span>
      </div>

      <div className="explorer-panel">
        <div className="explorer-controls">
          <label>
            <span className="mono">ROTATE</span>
            <input
              type="range"
              min={-80}
              max={20}
              value={yaw}
              onChange={(e) => setYaw(Number(e.target.value))}
              aria-label="Rotate assembly horizontally"
            />
          </label>
          <label>
            <span className="mono">TILT</span>
            <input
              type="range"
              min={20}
              max={80}
              value={pitch}
              onChange={(e) => setPitch(Number(e.target.value))}
              aria-label="Tilt assembly"
            />
          </label>
          <label>
            <span className="mono">EXPLODE</span>
            <input
              type="range"
              min={0}
              max={2}
              step={0.01}
              value={explode}
              onChange={(e) => setExplode(Number(e.target.value))}
              aria-label="Separate assembly layers"
            />
          </label>
          <div className="explorer-buttons">
            <button type="button" onClick={() => { setYaw(-28); setPitch(58); setExplode(1); }}>
              <RotateCcw size={13} aria-hidden="true" />Reset
            </button>
            <button type="button" onClick={() => setExplode(explode > 0.2 ? 0 : 1.4)}>
              {explode > 0.2 ? <Minimize2 size={13} aria-hidden="true" /> : <Layers size={13} aria-hidden="true" />}
              {explode > 0.2 ? "Collapse" : "Explode"}
            </button>
          </div>
        </div>

        <ol className="explorer-list">
          {deviceComponents.map((c) => (
            <li key={c.id}>
              <button type="button" aria-pressed={selected === c.id} onClick={() => setSelected(selected === c.id ? null : c.id)}>
                <span className="mono">{c.code.split(" / ")[0]}</span>
                <span className="explorer-list-name">{c.name}</span>
                <span className="explorer-role">{c.role}</span>
              </button>
            </li>
          ))}
        </ol>

        <div className="explorer-detail" aria-live="polite">
          {part ? (
            <>
              <span className="mono">{part.code}</span>
              <h4>{part.name}</h4>
              <p>{part.detail}</p>
              <dl>
                <div><dt className="mono">ROLE</dt><dd>{part.role}</dd></div>
                <div><dt className="mono">SPEC</dt><dd>{part.spec}</dd></div>
              </dl>
            </>
          ) : (
            <p className="fine-print">Select a component to inspect its role in the signal path.</p>
          )}
        </div>
      </div>
    </div>
  );
}
