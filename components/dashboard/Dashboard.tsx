"use client";

import { useCallback, useMemo, useState, type CSSProperties } from "react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Activity, ArrowUpRight, Download, Clock3, Check, Info, FileText } from "lucide-react";
import Link from "next/link";
import { DemoBadge } from "@/components/ui/Primitives";
import { useTheme } from "@/components/ui/Providers";
import { TimeMachine } from "./TimeMachine";
import { BilateralMirror } from "./BilateralMirror";
import { RecoveryReceipt } from "./RecoveryReceipt";
import {
  baseline,
  contributions,
  gaitFor,
  sessions as demoSessions,
  whatChanged,
  whatMatters,
  type Session,
} from "@/lib/demo-data";

function exportReport() {
  const rows = [
    "RehabSense - ILLUSTRATIVE INTERFACE DATA - NOT A CLINICAL REPORT",
    "These values are invented to demonstrate an interface. They are not measurements.",
    "",
    "Session,Day,Composite indicator (/100),Estimated knee ROM (deg),Bilateral symmetry (%),Estimated cadence (steps/min),Repetitions,Duration,Illustrative confidence,Data coverage (%)",
    ...demoSessions.map(
      (s) =>
        `${s.label},${s.dayLabel},${s.score},${s.rom},${s.symmetry},${s.cadence},${s.reps},${s.duration},${s.confidence},${s.coverage}`,
    ),
    "",
    "Estimated decision-support indicators. Does not replace clinical evaluation.",
  ];
  const url = URL.createObjectURL(
    new Blob([rows.join("\n")], { type: "text/csv;charset=utf-8;" }),
  );
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = "rehabsense-illustrative-report.csv";
  anchor.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function Dashboard({ standalone = false }: { standalone?: boolean }) {
  const [view, setView] = useState<"patient" | "physio">("patient");
  const [scrub, setScrub] = useState(demoSessions.length - 1);
  const [selected, setSelected] = useState<Session>(demoSessions[demoSessions.length - 1]);
  const [range, setRange] = useState("all");
  const [table, setTable] = useState(false);
  const [receipt, setReceipt] = useState(false);
  const { theme } = useTheme();

  const sessions = demoSessions;
  const session = selected;
  const gait = useMemo(() => gaitFor(session), [session]);
  const changed = useMemo(() => whatChanged(baseline, session), [session]);
  const matters = useMemo(() => whatMatters(session), [session]);

  const onSettle = useCallback((next: Session) => setSelected(next), []);
  const cyan = theme === "dark" ? "#38e8ff" : "#00718f";
  const violet = theme === "dark" ? "#b49aff" : "#5b3fc4";
  const tick = theme === "dark" ? "#93a3bd" : "#5a6a80";
  const chartData = useMemo(() => (range === "recent" ? sessions.slice(-3) : sessions), [range, sessions]);

  const tooltipStyle = {
    background: "var(--raised)",
    border: "1px solid var(--line)",
    borderRadius: 10,
    color: "var(--text)",
    fontSize: 12,
    boxShadow: "var(--shadow-soft)",
  };

  return (
    <div className={`dashboard-frame ${standalone ? "standalone" : ""}`}>
      <div className="browser-bar">
        <span className="browser-dots" aria-hidden="true">
          <i />
          <i />
          <i />
        </span>
        <span className="mono browser-title">REHABSENSE / MOVEMENT INTELLIGENCE</span>
        <span className="connected">
          <span aria-hidden="true" /> Demo workspace
        </span>
      </div>

      <div className="dashboard-toolbar">
        <div>
          <p className="eyebrow">YOUR RECOVERY, IN CONTEXT</p>
          <h3>
            {view === "patient"
              ? "Every session tells a story."
              : "Look beyond a single assessment."}
          </h3>
        </div>
        <div className="segmented" role="group" aria-label="Dashboard view">
          <button type="button" aria-pressed={view === "patient"} onClick={() => setView("patient")}>
            Patient view
          </button>
          <button type="button" aria-pressed={view === "physio"} onClick={() => setView("physio")}>
            Physiotherapist view
          </button>
        </div>
      </div>

      <div className="dashboard-subline">
        <DemoBadge />
        <span className="mono">
          {session.label} · {session.dayLabel}
        </span>
      </div>

      <div className="dashboard-grid">
        <div className="dash-score">
          <div className="eyebrow">RECOVERY INDICATOR</div>
          <div className="mini-score" style={{ "--score": `${session.score}%` } as CSSProperties}>
            <div>
              <strong>{session.score}</strong>
              <span>of 100 · estimated</span>
            </div>
          </div>
          <p>A composite view, not a clinical verdict.</p>
          <div className="score-factors">
            <span className="mono">CONTRIBUTING FACTORS</span>
            {contributions(session).map((f) => (
              <div key={f.key}>
                <span>{f.label}</span>
                <div className="factor-bar" aria-hidden="true">
                  <i style={{ width: `${f.value}%`, background: f.color }} />
                </div>
                <strong>{f.value}</strong>
              </div>
            ))}
            <span className="fine-print">
              Weights follow the proposed model. Values are illustrative.
            </span>
          </div>
          <span className={`confidence confidence-${session.confidence.toLowerCase()}`}>
            <Check size={13} aria-hidden="true" /> {session.confidence} illustrative confidence
          </span>
          <div className="coverage-row">
            <span>Data coverage</span>
            <div className="coverage-bar" aria-hidden="true">
              <i style={{ width: `${session.coverage}%` }} />
            </div>
            <strong>{session.coverage}%</strong>
          </div>
        </div>

        <div className="dash-main">
          <div className="metric-row">
            <div>
              <span>Estimated knee ROM</span>
              <strong>
                {session.rom}
                <small>°</small>
              </strong>
            </div>
            <div>
              <span>Estimated cadence</span>
              <strong>
                {session.cadence}
                <small>steps/min</small>
              </strong>
            </div>
            <div>
              <span>Repetitions</span>
              <strong>
                {session.reps}
                <small>reps</small>
              </strong>
            </div>
            <div>
              <span>Session duration</span>
              <strong>
                {session.duration}
                <small>min:sec</small>
              </strong>
            </div>
          </div>

          <div className="chart-heading">
            <h4>Left and right. One movement.</h4>
            <span className="legend">
              <i className="legend-left" />
              Left
              <i className="legend-right" />
              Right
            </span>
          </div>
          <div
            className="chart-area"
            role="img"
            aria-label="Illustrative left and right estimated knee angles across a normalized gait cycle. Both curves rise to roughly 55 to 58 degrees near mid-cycle and follow a similar shape, with the right limb slightly lower through the first half."
          >
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={gait} margin={{ top: 10, right: 10, bottom: 0, left: -22 }}>
                <CartesianGrid vertical={false} stroke="var(--line)" strokeDasharray="3 6" />
                <XAxis
                  dataKey="cycle"
                  tick={{ fill: tick, fontSize: 10 }}
                  tickLine={false}
                  axisLine={false}
                  tickFormatter={(v) => `${v}%`}
                />
                <YAxis
                  tick={{ fill: tick, fontSize: 10 }}
                  tickLine={false}
                  axisLine={false}
                  tickFormatter={(v) => `${v}°`}
                />
                <Tooltip contentStyle={tooltipStyle} labelFormatter={(v) => `Gait cycle: ${v}%`} />
                <Line
                  type="monotone"
                  dataKey="left"
                  name="Left estimate (°)"
                  stroke={cyan}
                  strokeWidth={2.4}
                  dot={false}
                  isAnimationActive={false}
                />
                <Line
                  type="monotone"
                  dataKey="right"
                  name="Right estimate (°)"
                  stroke={violet}
                  strokeDasharray="5 4"
                  strokeWidth={2}
                  dot={false}
                  isAnimationActive={false}
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
          <p className="chart-caption">
            Normalized gait cycle (%) · Estimated knee angle (°) · Illustrative interface data
          </p>
        </div>

        <div className="trend-panel">
          <div className="chart-heading">
            <h4>Recovery over time</h4>
            <label className="sr-only" htmlFor="trend-range">
              Trend range
            </label>
            <select id="trend-range" value={range} onChange={(e) => setRange(e.target.value)}>
              <option value="all">All demo sessions</option>
              <option value="recent">Last 3 sessions</option>
            </select>
          </div>
          <div
            className="trend-chart"
            role="img"
            aria-label="Illustrative composite recovery indicator across five demo sessions: 61, 66, 69, then a dip to 68 on a session with lower data coverage, then 76. Progress is shown as uneven on purpose. This is not a measured product outcome."
          >
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={chartData} margin={{ top: 12, right: 10, left: -22, bottom: 0 }}>
                <defs>
                  <linearGradient id="trendFill" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor={cyan} stopOpacity={theme === "dark" ? 0.32 : 0.22} />
                    <stop offset="100%" stopColor={cyan} stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid vertical={false} stroke="var(--line)" strokeDasharray="3 6" />
                <XAxis dataKey="dayLabel" tick={{ fill: tick, fontSize: 10 }} tickLine={false} axisLine={false} />
                <YAxis domain={[40, 100]} tick={{ fill: tick, fontSize: 10 }} tickLine={false} axisLine={false} />
                <Tooltip contentStyle={tooltipStyle} />
                <Area
                  dataKey="score"
                  name="Illustrative indicator"
                  type="monotone"
                  stroke={cyan}
                  strokeWidth={2.4}
                  fill="url(#trendFill)"
                  dot={{ r: 3, fill: cyan, strokeWidth: 0 }}
                  isAnimationActive={false}
                />
              </AreaChart>
            </ResponsiveContainer>
          </div>
          <p className="chart-caption">Recovery is rarely a straight line. Session 04 shows a dip.</p>
        </div>

        <div className="session-panel">
          <div className="chart-heading">
            <h4>Session timeline</h4>
            <Clock3 size={15} aria-hidden="true" />
          </div>
          <div className="session-list">
            {sessions.map((s) => (
              <button
                key={s.id}
                type="button"
                onClick={() => {
                  setSelected(s);
                  setScrub(sessions.indexOf(s));
                }}
                aria-pressed={session.id === s.id}
              >
                <span className="session-marker" aria-hidden="true" />
                <span className="session-label">
                  {s.label}
                  <small>{s.dayLabel}</small>
                </span>
                <strong>{s.score}</strong>
              </button>
            ))}
          </div>
        </div>
      </div>

      <TimeMachine index={scrub} onIndex={setScrub} onSettle={onSettle} />

      <div className="insight-layer">
        <div className="insight-block">
          <span className="eyebrow">WHAT CHANGED</span>
          <ul>
            {changed.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
          <span className="fine-print">Compared with {baseline.label} ({baseline.dayLabel}).</span>
        </div>
        <div className="insight-block insight-matters">
          <span className="eyebrow">WHAT MATTERS</span>
          <strong>{matters.heading}</strong>
          <p>{matters.body}</p>
        </div>
      </div>

      <BilateralMirror current={session} />

      <div className="review-note">
        <Info size={17} aria-hidden="true" />
        <p>
          {view === "physio"
            ? "Review context: session 04 has lower data coverage (58%). Interpret estimated metrics alongside coverage, exercise context and clinical assessment."
            : "A little context matters. Session 04 recorded less of the movement than the others, so its indicator is less dependable. Your physiotherapist can help interpret what it means."}
        </p>
      </div>

      {view === "physio" && (
        <div className="clinician-detail">
          <Activity size={18} aria-hidden="true" />
          <p>
            <strong>Session quality review</strong>
            <br />
            Compare both limbs, review signal coverage, and discuss the pattern with the patient.
            No autonomous diagnosis is generated and no clearance decision is implied.
          </p>
        </div>
      )}

      <div className="dashboard-bottom">
        <button type="button" className="text-link" onClick={() => setTable(!table)} aria-expanded={table}>
          {table ? "Hide" : "Show"} accessible data table
        </button>
        <button type="button" className="text-link" onClick={() => setReceipt(true)}>
          <FileText size={15} aria-hidden="true" />
          Open recovery receipt
        </button>
        <button type="button" className="text-link" onClick={exportReport}>
          <Download size={15} aria-hidden="true" />
          Export illustrative CSV
        </button>
        {!standalone && (
          <Link className="text-link" href="/dashboard">
            Open workspace
            <ArrowUpRight size={15} aria-hidden="true" />
          </Link>
        )}
      </div>

      {table && (
        <div className="table-scroll">
          <table>
            <caption>Illustrative session values — not clinical measurements</caption>
            <thead>
              <tr>
                <th scope="col">Session</th>
                <th scope="col">Indicator /100</th>
                <th scope="col">ROM estimate</th>
                <th scope="col">Cadence estimate</th>
                <th scope="col">Repetitions</th>
                <th scope="col">Coverage</th>
              </tr>
            </thead>
            <tbody>
              {sessions.map((s) => (
                <tr key={s.id}>
                  <th scope="row">{s.label}</th>
                  <td>{s.score}</td>
                  <td>{s.rom}°</td>
                  <td>{s.cadence} steps/min</td>
                  <td>{s.reps}</td>
                  <td>{s.coverage}%</td>
                </tr>
              ))}
            </tbody>
          </table>
          <table>
            <caption>Illustrative bilateral gait samples</caption>
            <thead>
              <tr>
                <th scope="col">Gait cycle</th>
                <th scope="col">Left estimate</th>
                <th scope="col">Right estimate</th>
              </tr>
            </thead>
            <tbody>
              {gait.map((s) => (
                <tr key={s.cycle}>
                  <th scope="row">{s.cycle}%</th>
                  <td>{s.left}°</td>
                  <td>{s.right}°</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <RecoveryReceipt session={session} open={receipt} onClose={() => setReceipt(false)} />
    </div>
  );
}
