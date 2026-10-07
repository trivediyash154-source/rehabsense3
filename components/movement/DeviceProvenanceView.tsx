"use client";

import { Cpu } from "lucide-react";
import { movementApi, useApi } from "@/lib/api/movement";
import { dateTime, num } from "@/lib/movement-format";
import { Failure, Loading, Panel } from "./Bits";
import { PROVENANCE_BADGE, ProvenanceBadge, ProvenanceLegend } from "./Provenance";

/**
 * Every device the server has seen, with where its data comes from. Demo and
 * replay sources are simulators by declaration: they are never shown as a
 * connected physical ESP32.
 */
export function DeviceProvenanceView() {
  const { data, error, loading, reload } = useApi(movementApi.devices, []);
  const devices = data?.items ?? [];
  const physical = devices.filter((d) => d.provenance === "PHYSICAL_REGISTERED");
  return (
    <>
      <Panel eyebrow="DATA SOURCES" title="Where a recording's samples can come from"
        footer="Decided once, at the device handshake, from authentication — never from the data and never from a device name. Only REAL HARDWARE (a registered device with its own key) counts as hardware evidence.">
        <ProvenanceLegend />
      </Panel>

      <Panel eyebrow="DEVICES" title={`${devices.length} known · ${physical.length} registered physical`}>
        {loading && !data ? <Loading what="devices" /> : error ? <Failure error={error} retry={reload} /> : devices.length === 0 ? (
          <p className="mv-empty">No device has connected yet.</p>
        ) : (
          <ul className="mv-devices">
            {devices.map((d) => {
              const nonPhysical = d.provenance && ["SYNTHETIC_DEMONSTRATION", "PUBLIC_DATASET_REPLAY", "SIMULATED"].includes(d.provenance);
              return (
                <li key={d.id} className={nonPhysical ? "is-virtual" : ""}>
                  <Cpu size={18} aria-hidden="true" />
                  <div className="mv-device-copy">
                    <strong className="mono">{d.device_id}</strong>
                    <span className="fine-print">
                      {nonPhysical
                        ? `${PROVENANCE_BADGE[d.provenance!]?.label.toLowerCase()} source — not a physical ESP32`
                        : d.verified_hardware ? "registered device" : "unregistered device"}
                      {" · "}firmware {d.firmware_version ?? "—"} · protocol v{d.protocol_version ?? "—"}
                      {d.sample_rate_hz ? ` · ${num(d.sample_rate_hz, 0)} Hz` : ""}
                    </span>
                    <span className="fine-print">
                      {d.sensors.length} sensor channels ({d.sensors.map((s) => s.capability.replace(/_/g, " ")).join(", ") || "none declared"})
                      {Object.keys(d.recordings_by_provenance).length > 0 &&
                        ` · recordings: ${Object.entries(d.recordings_by_provenance).map(([p, n]) => `${n} ${PROVENANCE_BADGE[p]?.label.toLowerCase() ?? p}`).join(", ")}`}
                    </span>
                  </div>
                  <ProvenanceBadge value={d.provenance} compact />
                  <span className={`mv-device-state ${d.status === "ONLINE" && !nonPhysical ? "is-online" : ""}`}>
                    {nonPhysical ? "not a physical device" : d.status.toLowerCase()}
                    <small>last seen {dateTime(d.last_seen)}</small>
                  </span>
                </li>
              );
            })}
          </ul>
        )}
      </Panel>
    </>
  );
}
