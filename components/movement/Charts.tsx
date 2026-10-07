"use client";

import { useMemo } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
  ZAxis,
} from "recharts";
import { useTheme } from "@/components/ui/Providers";
import { activityLabel, num, shares } from "@/lib/movement-format";

/** Resolved colours: SVG presentation attributes do not see CSS variables. */
export function useChartColors() {
  const { theme } = useTheme();
  return useMemo(
    () =>
      theme === "light"
        ? {
            cyan: "#00718f", teal: "#00806e", violet: "#5b3fc4", amber: "#9a5c1f", coral: "#b0443c",
            blue: "#2358d6", magenta: "#a3308f", tick: "#5a6a80", grid: "#dbe5ef", ink: "#0a1628",
            series: ["#00806e", "#5b3fc4", "#2358d6", "#9a5c1f", "#a3308f", "#00718f"],
          }
        : {
            cyan: "#38e8ff", teal: "#3fe0bb", violet: "#b49aff", amber: "#ecb87d", coral: "#ff9d92",
            blue: "#6aa4ff", magenta: "#e881d6", tick: "#93a3bd", grid: "rgba(163,190,232,0.22)", ink: "#f4f8ff",
            series: ["#3fe0bb", "#b49aff", "#6aa4ff", "#ecb87d", "#e881d6", "#38e8ff"],
          },
    [theme],
  );
}

export const tooltipStyle = {
  background: "var(--raised)",
  border: "1px solid var(--line)",
  borderRadius: 10,
  color: "var(--text)",
  fontSize: 12,
  boxShadow: "var(--shadow-soft)",
};

export type SeriesDef = { key: string; label: string; color: string; dashed?: boolean };

const day = (ms: number) => new Date(ms).toLocaleDateString(undefined, { day: "numeric", month: "short" });

/**
 * Values over time. `x` is epoch milliseconds; a null y is a gap, never a 0.
 */
export function TrendChart({
  data,
  series,
  height = 220,
  unit = "",
  domain,
  reference,
  onSelect,
  digits = 1,
}: {
  data: Record<string, number | null | string>[];
  series: SeriesDef[];
  height?: number;
  unit?: string;
  domain?: [number | "auto" | "dataMin" | "dataMax", number | "auto" | "dataMin" | "dataMax"];
  reference?: { y: number; label: string };
  onSelect?: (datum: Record<string, unknown>) => void;
  digits?: number;
}) {
  const c = useChartColors();
  if (!data.length) return <p className="mv-empty">No values recorded yet.</p>;
  return (
    <div className="mv-chart" style={{ height }}>
      <ResponsiveContainer width="100%" height="100%">
        <LineChart
          data={data}
          margin={{ top: 10, right: 14, bottom: 0, left: -14 }}
          onClick={(state) => {
            const payload = (state as { activePayload?: { payload: Record<string, unknown> }[] } | null)
              ?.activePayload?.[0]?.payload;
            if (payload && onSelect) onSelect(payload);
          }}
        >
          <CartesianGrid vertical={false} stroke={c.grid} strokeDasharray="3 6" />
          <XAxis
            dataKey="x"
            type="number"
            scale="time"
            domain={["dataMin", "dataMax"]}
            tickFormatter={day}
            tick={{ fill: c.tick, fontSize: 10 }}
            axisLine={false}
            tickLine={false}
            minTickGap={24}
          />
          <YAxis
            domain={domain ?? ["auto", "auto"]}
            tick={{ fill: c.tick, fontSize: 10 }}
            axisLine={false}
            tickLine={false}
            width={44}
            tickFormatter={(v: number) => `${Math.round(v)}${unit}`}
          />
          {reference && (
            <ReferenceLine y={reference.y} stroke={c.tick} strokeDasharray="4 4" label={{
              value: reference.label, fill: c.tick, fontSize: 10, position: "insideTopRight",
            }} />
          )}
          <Tooltip
            contentStyle={tooltipStyle}
            labelFormatter={(v) => new Date(Number(v)).toLocaleString(undefined, {
              day: "numeric", month: "short", hour: "2-digit", minute: "2-digit",
            })}
            formatter={(value: number, name: string) => [`${num(value, digits)}${unit}`, name]}
          />
          {series.map((s) => (
            <Line
              key={s.key}
              type="monotone"
              dataKey={s.key}
              name={s.label}
              stroke={s.color}
              strokeWidth={2}
              strokeDasharray={s.dashed ? "5 5" : undefined}
              dot={{ r: 3, fill: s.color, strokeWidth: 0 }}
              activeDot={{ r: 5 }}
              connectNulls
              isAnimationActive={false}
            />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

/** A tiny inline trend: one value per session, nulls skipped. */
export function Sparkline({
  values,
  color = "var(--teal)",
  width = 96,
  height = 26,
  domain,
}: {
  values: (number | null)[];
  color?: string;
  width?: number;
  height?: number;
  domain?: [number, number];
}) {
  const pts = values
    .map((v, i) => (v == null ? null : ([i, v] as const)))
    .filter((p): p is readonly [number, number] => p !== null);
  if (pts.length < 2) return <span className="mv-spark-empty">—</span>;
  const lo = domain?.[0] ?? Math.min(...pts.map((p) => p[1]));
  const hi = domain?.[1] ?? Math.max(...pts.map((p) => p[1]));
  const span = hi - lo || 1;
  const last = values.length - 1 || 1;
  const xy = pts.map(([i, v]) => [2 + ((width - 4) * i) / last, height - 3 - ((height - 6) * (v - lo)) / span]);
  const d = xy.map(([x, y], k) => `${k ? "L" : "M"}${x.toFixed(1)} ${y.toFixed(1)}`).join(" ");
  const [ex, ey] = xy[xy.length - 1];
  return (
    <svg className="mv-spark" width={width} height={height} viewBox={`0 0 ${width} ${height}`} aria-hidden="true">
      <path d={d} fill="none" stroke={color} strokeWidth={1.6} strokeLinejoin="round" strokeLinecap="round" />
      <circle cx={ex} cy={ey} r={2.4} fill={color} />
    </svg>
  );
}

/** Horizontal share bars, e.g. activity-model output by time. */
export function DistributionBars({
  seconds,
  top = 6,
  emptyText = "No classified windows.",
}: {
  seconds: Record<string, number> | null | undefined;
  top?: number;
  emptyText?: string;
}) {
  const rows = shares(seconds, top);
  if (!rows.length) return <p className="mv-empty">{emptyText}</p>;
  return (
    <ul className="mv-bars">
      {rows.map((r) => (
        <li key={r.key}>
          <span className="mv-bars-label">{r.label}</span>
          <span className="mv-bars-track" aria-hidden="true">
            <i style={{ width: `${Math.max(1, r.share * 100)}%` }} />
          </span>
          <span className="mv-bars-value mono">{r.share < 0.005 ? "<1%" : `${Math.round(r.share * 100)}%`}</span>
        </li>
      ))}
    </ul>
  );
}

export function Histogram({
  bins,
  color,
  height = 170,
  unit = "",
}: {
  bins: { from: number; to: number; count: number }[];
  color: string;
  height?: number;
  unit?: string;
}) {
  const c = useChartColors();
  const fine = bins.length > 0 && bins[bins.length - 1].to <= 1;
  const fmt = (x: number) => (fine ? x.toFixed(1) : String(Math.round(x)));
  const data = bins.map((b) => ({ label: `${fmt(b.from)}${unit}`, count: b.count, range: `${fmt(b.from)}–${fmt(b.to)}${unit}` }));
  return (
    <div className="mv-chart" style={{ height }}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: -20 }}>
          <CartesianGrid vertical={false} stroke={c.grid} strokeDasharray="3 6" />
          <XAxis dataKey="label" tick={{ fill: c.tick, fontSize: 9 }} axisLine={false} tickLine={false} interval={1} />
          <YAxis allowDecimals={false} tick={{ fill: c.tick, fontSize: 10 }} axisLine={false} tickLine={false} />
          <Tooltip
            contentStyle={tooltipStyle}
            cursor={{ fill: "rgba(127,127,127,0.08)" }}
            labelFormatter={(_, payload) => String(payload?.[0]?.payload?.range ?? "")}
            formatter={(v: number) => [v, "sessions"]}
          />
          <Bar dataKey="count" fill={color} radius={[4, 4, 0, 0]} isAnimationActive={false} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

export function QualityScatter({
  points,
  colorFor,
  height = 240,
}: {
  points: { x: number; y: number; group: string }[];
  colorFor: (group: string) => string;
  height?: number;
}) {
  const c = useChartColors();
  const groups = Array.from(new Set(points.map((p) => p.group)));
  return (
    <div className="mv-chart" style={{ height }}>
      <ResponsiveContainer width="100%" height="100%">
        <ScatterChart margin={{ top: 10, right: 14, bottom: 4, left: -12 }}>
          <CartesianGrid stroke={c.grid} strokeDasharray="3 6" />
          <XAxis type="number" dataKey="x" name="Asymmetry" unit="%" tick={{ fill: c.tick, fontSize: 10 }}
            axisLine={false} tickLine={false} domain={[0, "auto"]} />
          <YAxis type="number" dataKey="y" name="MQI" tick={{ fill: c.tick, fontSize: 10 }}
            axisLine={false} tickLine={false} domain={["auto", 100]} width={44} />
          <ZAxis range={[36, 36]} />
          <Tooltip contentStyle={tooltipStyle} cursor={{ strokeDasharray: "3 3" }}
            formatter={(v: number, name: string) => [num(v, 1), name]} />
          {groups.map((g) => (
            <Scatter key={g} name={g} data={points.filter((p) => p.group === g)} fill={colorFor(g)}
              fillOpacity={0.75} isAnimationActive={false} />
          ))}
        </ScatterChart>
      </ResponsiveContainer>
    </div>
  );
}

const ACTIVITY_TONE: Record<string, string> = {
  walking: "var(--teal)",
  standing: "var(--blue)",
  sitting: "var(--violet)",
  other_exercise: "var(--amber)",
  stairs_up: "var(--cyan)",
  stairs_down: "var(--magenta)",
  cycling: "var(--coral)",
  lying: "var(--muted)",
  running: "var(--coral)",
};

export function activityTone(activity: string | null | undefined): string {
  return (activity && ACTIVITY_TONE[activity]) || "var(--muted)";
}

/** Model output over session time: one coloured span per segment. */
export function ActivityTimeline({
  segments,
  duration,
  cursor,
}: {
  segments: { t_start: number; t_end: number; activity: string | null; status: string }[];
  duration: number;
  cursor?: number | null;
}) {
  const total = Math.max(duration, ...segments.map((s) => s.t_end), 1);
  const seen = Array.from(new Set(segments.map((s) => (s.status === "OK" ? s.activity : null))));
  return (
    <div className="mv-timeline">
      <div className="mv-timeline-track">
        {segments.map((s, i) => (
          <span
            key={`${s.t_start}-${i}`}
            className={s.status === "OK" ? "" : "is-uncertain"}
            title={`${activityLabel(s.activity)} · ${s.status} · ${s.t_start.toFixed(1)}–${s.t_end.toFixed(1)} s`}
            style={{
              left: `${(100 * s.t_start) / total}%`,
              width: `${Math.max(0.4, (100 * (s.t_end - s.t_start)) / total)}%`,
              background: s.status === "OK" ? activityTone(s.activity) : undefined,
            }}
          />
        ))}
        {cursor != null && <i className="mv-timeline-cursor" style={{ left: `${(100 * cursor) / total}%` }} />}
      </div>
      <ul className="mv-timeline-legend">
        {seen.map((a) => (
          <li key={a ?? "uncertain"}>
            <i style={{ background: a ? activityTone(a) : undefined }} className={a ? "" : "is-uncertain"} />
            {a ? activityLabel(a) : "Low confidence / no result"}
          </li>
        ))}
      </ul>
    </div>
  );
}
